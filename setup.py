import hashlib
import json
import os
import subprocess
import time

import requests

# Constants
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USER = "dmzoneill"
REPO_LIST_URL = "https://api.github.com/user/repos?affiliation=owner&per_page=100"
SECRETS = [
    "PROFILE_HOOK",
    "AI_API_KEY",
    "AI_MODEL",
    "GOOGLE_APPLICATION_CREDENTIALS_JSON",
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLAUDE_CODE_USE_VERTEX",
    "TELEGRAM_ISSUES_CHAT_ID",
    "DOCKER_TOKEN",
    "PYPI_TOKEN",
    "WORDPRESS_APPLICATION",
    "WORDPRESS_PASSWORD",
    "WORDPRESS_URL",
    "WORDPRESS_USERNAME",
    "YOUTUBE_API",
    "UNSPLASH_ACCESS_KEY",
    "CI_USERNAME",
    "CI_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "SNAPCRAFT_STORE_CREDENTIALS",
    "CACHIX_AUTH_TOKEN",
    "AUR_SSH_PRIVATE_KEY",
    "HOMEBREW_TAP_TOKEN",
    "CHOCOLATEY_API_KEY",
    "SCOOP_BUCKET_TOKEN",
    "WINGET_TOKEN",
]

HASH_VAR_NAME = "SECRETS_HASH"

# Headers for GitHub API requests
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# Rate limit delay between API calls (seconds)
API_DELAY = 1
GH_CLI_DELAY = 2


def hash_value(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def compute_per_secret_hashes(secrets):
    return {
        key: hash_value(value)
        for key, value in secrets.items()
        if value is not None
    }


def rate_limited_get(url, max_retries=3):
    for attempt in range(max_retries):
        time.sleep(API_DELAY)
        response = requests.get(url, headers=headers)
        if response.status_code in (403, 429):
            retry_after = int(response.headers.get("Retry-After", 60))
            print(
                f"  Rate limited, waiting {retry_after}s "
                f"(attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(retry_after)
            continue
        return response
    return response


def authenticate_gh():
    os.environ.pop("GITHUB_TOKEN", None)

    with open(".githubtoken", "w") as f:
        f.write(f"{GITHUB_TOKEN}")

    subprocess.run(
        ["gh", "auth", "login", "--with-token"],
        input=open(".githubtoken").read(),
        text=True,
        check=True,
    )

    os.remove(".githubtoken")


def set_secret(repo_name, secret, value):
    cmd = [
        "gh",
        "secret",
        "set",
        secret,
        "-R",
        f"{GITHUB_USER}/{repo_name}",
        "-b",
        value,
    ]

    try:
        time.sleep(GH_CLI_DELAY)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"    Set {secret}")
    except subprocess.CalledProcessError as e:
        print(f"    Failed to set {secret}: {e.stderr}")


def get_remote_hashes(repo_name):
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}"
        f"/actions/variables/{HASH_VAR_NAME}"
    )
    response = rate_limited_get(url)
    if response.status_code == 200:
        try:
            return json.loads(response.json().get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def set_repo_variable(repo_name, name, value):
    repo_full = f"{GITHUB_USER}/{repo_name}"
    url = (
        f"https://api.github.com/repos/{repo_full}"
        f"/actions/variables/{name}"
    )
    time.sleep(API_DELAY)
    response = requests.patch(url, headers=headers, json={"value": value})
    if response.status_code == 204:
        print(f"    Updated hash variable")
        return

    url = f"https://api.github.com/repos/{repo_full}/actions/variables"
    time.sleep(API_DELAY)
    response = requests.post(
        url, headers=headers, json={"name": name, "value": value}
    )
    if response.status_code == 201:
        print(f"    Created hash variable")
    else:
        print(
            f"    Failed to set variable {name}: {response.status_code} "
            f"{response.text}"
        )


def set_secrets_with_gh(repo_name, secrets, current_hashes):
    remote_hashes = get_remote_hashes(repo_name)

    changed = []
    for key, current_hash in current_hashes.items():
        if remote_hashes.get(key) != current_hash:
            changed.append(key)

    if not changed:
        print(f"  All secrets up to date, skipping")
        return

    print(f"  {len(changed)} secret(s) changed: {', '.join(changed)}")

    for key in changed:
        set_secret(repo_name, key, secrets[key])

    set_repo_variable(repo_name, HASH_VAR_NAME, json.dumps(current_hashes))


def get_repositories():
    page = 1
    repos = []
    while True:
        response = rate_limited_get(f"{REPO_LIST_URL}&page={page}")
        if response.status_code == 200:
            repos_data = response.json()
            if not repos_data:
                break
            repos.extend(
                [repo["name"] for repo in repos_data if repo["name"] != "dmzoneill"]
            )
            page += 1
        else:
            print(f"Failed to fetch repositories, status code: {response.status_code}")
            break
    return repos


def main():
    secrets = {secret: os.getenv(secret) for secret in SECRETS}

    missing_secrets = [secret for secret, value in secrets.items() if value is None]
    if missing_secrets:
        print(f"Skipping unset secrets: {', '.join(missing_secrets)}")

    current_hashes = compute_per_secret_hashes(secrets)
    print(f"Computed hashes for {len(current_hashes)} secrets")

    authenticate_gh()

    repos = get_repositories()

    for repo in repos:
        if repo == "dmzoneill":
            continue
        print(f"\nSetting secrets for repository: {repo}")
        set_secrets_with_gh(repo, secrets, current_hashes)


if __name__ == "__main__":
    main()
