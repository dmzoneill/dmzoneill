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
HASH_VAR_NAME = "SECRETS_HASH"

# Headers for GitHub API requests
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# Rate limit delay between API calls (seconds)
API_DELAY = 1
GH_CLI_DELAY = 1.5

# Reserve buffer to avoid hitting the limit
RATE_LIMIT_RESERVE = 100


def hash_value(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def compute_per_secret_hashes(secrets):
    return {
        key: hash_value(value)
        for key, value in secrets.items()
        if value is not None
    }


def check_rate_limit():
    response = requests.get(
        "https://api.github.com/rate_limit", headers=headers
    )
    if response.status_code == 200:
        core = response.json()["resources"]["core"]
        remaining = core["remaining"]
        reset_time = core["reset"]
        print(f"  Rate limit: {remaining} remaining, resets at {reset_time}")
        return remaining
    return None


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
    response = requests.patch(
        url, headers=headers, json={"value": value}
    )
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
            f"    Failed to set variable {name}: "
            f"{response.status_code} {response.text}"
        )


def delete_secret(repo_name, secret):
    cmd = [
        "gh",
        "secret",
        "delete",
        secret,
        "-R",
        f"{GITHUB_USER}/{repo_name}",
    ]

    try:
        time.sleep(GH_CLI_DELAY)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"    Deleted {secret}")
    except subprocess.CalledProcessError as e:
        print(f"    Failed to delete {secret}: {e.stderr}")


def estimate_repo_cost(current_hashes, remote_hashes):
    changed = sum(
        1
        for k, v in current_hashes.items()
        if remote_hashes.get(k) != v
    )
    removed = sum(1 for k in remote_hashes if k not in current_hashes)
    if not changed and not removed:
        # 1 (fetch existing secrets) + some potential deprecated deletes
        return 5
    # changed*2 (gh secret set) + removed (delete) + 2 (set var) + 1 (fetch) + buffer
    return changed * 2 + removed + 5


def cleanup_deprecated_secrets(repo_name, existing_secrets, current_names):
    to_delete = [
        s for s in existing_secrets
        if s not in current_names and s != HASH_VAR_NAME
    ]
    if to_delete:
        print(
            f"  Cleaning up {len(to_delete)} deprecated secret(s): "
            f"{', '.join(to_delete)}"
        )
        for key in to_delete:
            delete_secret(repo_name, key)
    return to_delete


def fetch_existing_secret_names(repo_name):
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}"
        f"/actions/secrets"
    )
    response = rate_limited_get(url)
    if response.status_code == 200:
        return {
            s["name"] for s in response.json().get("secrets", [])
        }
    return set()


def sync_repo_secrets(repo_name, secrets, current_hashes, remote_hashes):
    changed = [
        key
        for key, h in current_hashes.items()
        if remote_hashes.get(key) != h
    ]
    removed = [k for k in remote_hashes if k not in current_hashes]

    existing = fetch_existing_secret_names(repo_name)
    deprecated = cleanup_deprecated_secrets(
        repo_name, existing, set(secrets.keys())
    )

    if not changed and not removed and not deprecated:
        print(f"  All secrets up to date, skipping")
        return

    if changed:
        print(
            f"  {len(changed)} secret(s) changed: {', '.join(changed)}"
        )
        for key in changed:
            set_secret(repo_name, key, secrets[key])

    if removed:
        print(
            f"  {len(removed)} secret(s) removed: {', '.join(removed)}"
        )
        for key in removed:
            delete_secret(repo_name, key)

    set_repo_variable(
        repo_name, HASH_VAR_NAME, json.dumps(current_hashes)
    )


def get_secret_names():
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/dmzoneill"
        f"/actions/secrets"
    )
    names = []
    while url:
        response = rate_limited_get(url)
        if response.status_code != 200:
            print(
                f"Failed to fetch secret names: {response.status_code}"
            )
            break
        data = response.json()
        names.extend(
            s["name"]
            for s in data.get("secrets", [])
            if s["name"] != HASH_VAR_NAME
        )
        url = response.links.get("next", {}).get("url")
    return names


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
                [
                    repo["name"]
                    for repo in repos_data
                    if repo["name"] != "dmzoneill"
                ]
            )
            page += 1
        else:
            print(
                f"Failed to fetch repositories, "
                f"status code: {response.status_code}"
            )
            break
    return repos


def main():
    secret_names = get_secret_names()
    if not secret_names:
        print("No secrets found on dmzoneill repo, aborting")
        return

    print(f"Found {len(secret_names)} secrets on dmzoneill repo")
    secrets = {name: os.getenv(name) for name in secret_names}

    missing_secrets = [
        secret for secret, value in secrets.items() if value is None
    ]
    if missing_secrets:
        print(f"Skipping unset secrets: {', '.join(missing_secrets)}")

    current_hashes = compute_per_secret_hashes(secrets)
    print(f"Computed hashes for {len(current_hashes)} secrets")

    authenticate_gh()

    repos = get_repositories()

    synced = 0
    skipped = 0
    for repo in repos:
        if repo == "dmzoneill":
            continue

        remaining = check_rate_limit()
        if remaining is None:
            remaining = RATE_LIMIT_RESERVE + 1

        remote_hashes = get_remote_hashes(repo)
        cost = estimate_repo_cost(current_hashes, remote_hashes)

        if cost > 0 and remaining < cost + RATE_LIMIT_RESERVE:
            print(
                f"\nSkipping {repo}: {remaining} calls left, "
                f"need {cost}+{RATE_LIMIT_RESERVE}"
            )
            skipped += 1
            continue

        print(f"\nSyncing secrets for: {repo} (est. cost: {cost})")
        sync_repo_secrets(
            repo, secrets, current_hashes, remote_hashes
        )
        synced += 1

    print(f"\nDone: synced {synced} repos")
    if skipped:
        print(
            f"Deferred {skipped} repos due to rate limit "
            f"(will resume next run)"
        )


if __name__ == "__main__":
    main()
