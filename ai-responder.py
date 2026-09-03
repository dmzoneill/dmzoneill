#!/usr/bin/env python3

import json
import os
import sys

import requests


def get_issue_content(repo, issue_number, github_token):
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["title"], data["body"] or "", data["html_url"], data["user"]["login"]


def get_pr_content(repo, pr_number, github_token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["title"], data["body"] or "", data["html_url"], data["user"]["login"]


def get_pr_diff(repo, pr_number, github_token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    diff = response.text
    if len(diff) > 10000:
        diff = diff[:10000] + "\n\n... (diff truncated)"
    return diff


def get_oauth_bearer_token(credentials_path):
    with open(credentials_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)

    refresh_token = cred_data.get("refresh_token")
    client_id = cred_data.get("client_id")
    client_secret = cred_data.get("client_secret")

    if not all([refresh_token, client_id, client_secret]):
        raise ValueError(
            "Invalid Google credentials file: missing client_id, client_secret, or refresh_token"
        )

    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    resp = requests.post(token_url, data=payload, timeout=15)
    resp.raise_for_status()
    token_json = resp.json()

    access_token = token_json.get("access_token")
    quota_project = cred_data.get("quota_project_id") or os.getenv(
        "GOOGLE_CLOUD_PROJECT"
    )
    return access_token, quota_project


def generate_opencode_reply(prompt_text, api_key):
    requested_model = os.getenv("OPENCODE_MODEL", "big-pickle")
    if requested_model.startswith("opencode/"):
        requested_model = requested_model[len("opencode/") :]
    elif requested_model.startswith("oc/"):
        requested_model = requested_model[len("oc/") :]

    candidate_models = [
        requested_model,
        "big-pickle",
        "mimo-v2.5-free",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    url = "https://opencode.ai/zen/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": 0.4,
            "max_tokens": 2048,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    content = msg.get("content")
                    if not content and "reasoning_content" in msg:
                        content = msg.get("reasoning_content")
                    if content:
                        return content.strip()
            elif response.status_code in (404, 429):
                last_error = (
                    f"Model {model} returned {response.status_code}: {response.text}"
                )
                continue
            else:
                last_error = (
                    f"OpenCode Zen API error ({response.status_code}): {response.text}"
                )
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(f"OpenCode Zen generation failed: {last_error}")


def generate_gemini_reply(prompt_text):
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    api_key = os.getenv("GEMINI_API_KEY")

    headers = {"Content-Type": "application/json"}
    query_params = ""

    if cred_path and os.path.exists(cred_path):
        access_token, quota_project = get_oauth_bearer_token(cred_path)
        headers["Authorization"] = f"Bearer {access_token}"
        if quota_project:
            headers["x-goog-user-project"] = quota_project
    elif api_key:
        query_params = f"?key={api_key}"
    else:
        raise RuntimeError(
            "Missing Gemini authentication: set GOOGLE_APPLICATION_CREDENTIALS or GEMINI_API_KEY."
        )

    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "gemini-flash-latest",
        "gemini-3.6-flash",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 2048,
        },
    }

    last_error = None
    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent{query_params}"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
            elif response.status_code == 404:
                last_error = f"Model {model} returned 404: {response.text}"
                continue
            else:
                last_error = (
                    f"Gemini API error ({response.status_code}): {response.text}"
                )
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(f"Gemini generation failed: {last_error}")


def generate_ai_reply(prompt_text):
    opencode_key = os.getenv("OPENCODE_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if opencode_key:
        try:
            return generate_opencode_reply(prompt_text, opencode_key)
        except Exception as e:
            print(f"OpenCode Zen generation failed: {e}", file=sys.stderr)
            if not (gemini_key or (cred_path and os.path.exists(cred_path))):
                raise

    if (cred_path and os.path.exists(cred_path)) or gemini_key:
        return generate_gemini_reply(prompt_text)

    raise RuntimeError(
        "Missing authentication: set OPENCODE_API_KEY, GEMINI_API_KEY, or GOOGLE_APPLICATION_CREDENTIALS."
    )


def post_comment(repo, number, comment, github_token, is_pr=False):
    if is_pr:
        url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.post(url, headers=headers, json={"body": comment}, timeout=10)
    response.raise_for_status()


def send_telegram(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        print("Telegram secrets not set, skipping notification")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"Telegram notification sent")
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")


def handle_issue():
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    issue_number = os.getenv("ISSUE_NUMBER")

    if not all([github_token, repo, issue_number]):
        raise RuntimeError("Missing required environment variables.")

    title, body, issue_url, author = get_issue_content(repo, issue_number, github_token)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ISSUES_CHAT_ID")
    message = (
        f"New issue on {repo}\n\nTitle: {title}\nBy: {author}\n\n{body}\n\n{issue_url}"
    )
    send_telegram(bot_token, chat_id, message)

    repo_url = os.getenv("ISSUE_REPO_URL", "")
    prompt = "You're a helpful AI assistant. Reply concisely to the following GitHub issue.\n"
    if repo_url:
        prompt += f"The source code is available at: {repo_url}\n"
    prompt += f"\n\n{title}\n\n{body}"

    comment = generate_ai_reply(prompt)
    post_comment(repo, issue_number, comment, github_token)


def handle_pr():
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    pr_number = os.getenv("PR_NUMBER")

    if not all([github_token, repo, pr_number]):
        raise RuntimeError("Missing required environment variables.")

    title, body, pr_url, author = get_pr_content(repo, pr_number, github_token)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_PR_CHAT_ID")
    message = f"New PR on {repo}\n\nTitle: {title}\nBy: {author}\n\n{body}\n\n{pr_url}"
    send_telegram(bot_token, chat_id, message)

    diff = get_pr_diff(repo, pr_number, github_token)
    repo_url = os.getenv("ISSUE_REPO_URL", "")
    prompt = "You're a helpful AI code reviewer. Review the following pull request concisely.\n"
    prompt += "Summarize the changes and flag any potential issues.\n"
    if repo_url:
        prompt += f"The source code is available at: {repo_url}\n"
    prompt += f"\nTitle: {title}\n\nDescription: {body}\n\nDiff:\n{diff}"

    comment = generate_ai_reply(prompt)
    post_comment(repo, pr_number, comment, github_token, is_pr=True)


def main():
    event_type = os.getenv("EVENT_TYPE", "issue")

    if event_type == "pull_request":
        handle_pr()
    else:
        handle_issue()


if __name__ == "__main__":
    main()
