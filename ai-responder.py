#!/usr/bin/env python3

import os
import subprocess
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


def generate_ai_reply(prompt_text):
    result = subprocess.run(
        ["claude", "--print"],
        input=prompt_text,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"Claude CLI stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Claude CLI failed with exit code {result.returncode}")

    return result.stdout.strip()


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
    message = f"New issue on {repo}\n\nTitle: {title}\nBy: {author}\n\n{body}\n\n{issue_url}"
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
