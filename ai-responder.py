#!/usr/bin/env python3

import json
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
    return data["title"], data["body"], data["html_url"], data["user"]["login"]


def generate_ai_reply(title, body, repo_url):
    prompt = (
        "You're a helpful AI assistant. Reply concisely to the following GitHub issue.\n"
    )
    if repo_url:
        prompt += f"The source code is available at: {repo_url}\n"

    issue_text = f"{title}\n\n{body}"

    result = subprocess.run(
        ["claude", "--print", "--prompt", f"{prompt}\n\n{issue_text}"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"Claude CLI stderr: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Claude CLI failed with exit code {result.returncode}")

    return result.stdout.strip()


def post_comment(repo, issue_number, comment, github_token):
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.post(url, headers=headers, json={"body": comment}, timeout=10)
    response.raise_for_status()


def send_telegram_notification(repo, title, issue_url, author):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ISSUES_CHAT_ID")

    if not bot_token or not chat_id:
        print("Telegram secrets not set, skipping notification")
        return

    message = f"New issue opened on {repo}\n\nTitle: {title}\nBy: {author}\n\n{body}\n\n{issue_url}"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"Telegram notification sent: {resp.json()}")
    except Exception as e:
        print(f"Failed to send Telegram notification: {e}")


def main():
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    issue_number = os.getenv("ISSUE_NUMBER")

    if not all([github_token, repo, issue_number]):
        raise RuntimeError("Missing required environment variables.")

    title, body, issue_url, author = get_issue_content(repo, issue_number, github_token)

    send_telegram_notification(repo, title, issue_url, author)

    repo_url = os.getenv("ISSUE_REPO_URL", "")
    comment = generate_ai_reply(title, body, repo_url)
    post_comment(repo, issue_number, comment, github_token)


if __name__ == "__main__":
    main()
