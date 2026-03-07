import hashlib
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

HASH_SECRET_NAME = "SECRETS_HASH"

# Headers for GitHub API requests
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# Rate limit delay between API calls (seconds)
API_DELAY = 1
GH_CLI_DELAY = 2


def compute_secrets_hash(secrets):
    combined = ""
    for key in sorted(secrets.keys()):
        value = secrets[key]
        if value is not None:
            combined += f"{key}={value}\n"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


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


def fetch_existing_secrets(repo_name):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/secrets"
    response = rate_limited_get(url)
    if response.status_code == 200:
        secrets = response.json()
        return {secret["name"] for secret in secrets["secrets"]}
    else:
        print(
            f"Failed to fetch existing secrets for {repo_name}, "
            f"status code: {response.status_code}"
        )
        return set()


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


def set_secrets_with_gh(repo_name, secrets, secrets_hash):
    existing_secrets = fetch_existing_secrets(repo_name)

    if HASH_SECRET_NAME in existing_secrets:
        # Hash exists — check if secrets need updating by comparing
        # We can't read the hash value via API, so we use a workaround:
        # if all expected secret names exist AND the hash secret exists,
        # we assume they're up to date. To force an update when values change,
        # we store the hash in a repo variable instead.
        pass

    # Check if repo has the hash variable matching current hash
    if repo_has_current_hash(repo_name, secrets_hash):
        print(f"  Secrets are up to date (hash matches), skipping")
        return

    print(f"  Secrets hash changed or missing, updating all secrets")

    for secret, value in secrets.items():
        if value is None:
            continue
        set_secret(repo_name, secret, value)

    # Store the hash as a repo variable (not secret, so we can read it back)
    set_repo_variable(repo_name, HASH_SECRET_NAME, secrets_hash)


def repo_has_current_hash(repo_name, expected_hash):
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}"
        f"/actions/variables/{HASH_SECRET_NAME}"
    )
    response = rate_limited_get(url)
    if response.status_code == 200:
        current_hash = response.json().get("value", "")
        return current_hash == expected_hash
    return False


def set_repo_variable(repo_name, name, value):
    repo_full = f"{GITHUB_USER}/{repo_name}"
    # Try to update first, create if it doesn't exist
    url = (
        f"https://api.github.com/repos/{repo_full}"
        f"/actions/variables/{name}"
    )
    time.sleep(API_DELAY)
    response = requests.patch(
        url, headers=headers, json={"value": value}
    )
    if response.status_code == 204:
        print(f"    Updated variable {name}")
        return

    # Variable doesn't exist, create it
    url = f"https://api.github.com/repos/{repo_full}/actions/variables"
    time.sleep(API_DELAY)
    response = requests.post(
        url, headers=headers, json={"name": name, "value": value}
    )
    if response.status_code == 201:
        print(f"    Created variable {name}")
    else:
        print(
            f"    Failed to set variable {name}: {response.status_code} "
            f"{response.text}"
        )


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

    secrets_hash = compute_secrets_hash(secrets)
    print(f"Current secrets hash: {secrets_hash}")

    authenticate_gh()

    repos = get_repositories()

    for repo in repos:
        if repo == "dmzoneill":
            continue
        print(f"\nSetting secrets for repository: {repo}")
        set_secrets_with_gh(repo, secrets, secrets_hash)


if __name__ == "__main__":
    main()
