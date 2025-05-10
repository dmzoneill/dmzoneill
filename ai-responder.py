#!/usr/bin/env python3

import os
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
    return data["title"], data["body"]

def generate_ai_reply(title, body, repo_url, openai_key):
    prompt = "You're a helpful AI assistant. Reply concisely to the following GitHub issue.\n"
    if repo_url:
        prompt += f"The source code is available at: {repo_url}\n"

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"{title}\n\n{body}"}
        ],
        "temperature": 0.5,
    }

    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def post_comment(repo, issue_number, comment, github_token):
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.post(url, headers=headers, json={"body": comment}, timeout=10)
    response.raise_for_status()

def main():
    openai_key = os.getenv("OPENAI_API_KEY")
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    issue_number = os.getenv("ISSUE_NUMBER")
    repo_url = os.getenv("ISSUE_REPO_URL", "")

    if not all([openai_key, github_token, repo, issue_number]):
        raise RuntimeError("Missing required environment variables.")

    title, body = get_issue_content(repo, issue_number, github_token)
    comment = generate_ai_reply(title, body, repo_url, openai_key)
    post_comment(repo, issue_number, comment, github_token)

if __name__ == "__main__":
    main()
