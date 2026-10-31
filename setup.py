import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

# Constants
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USER = "dmzoneill"
REPO_LIST_URL = "https://api.github.com/user/repos?affiliation=owner&per_page=100"
HASH_VAR_NAME = "SECRETS_HASH"
VARIABLES_HASH_VAR_NAME = "VARIABLES_HASH"
# Copied from hub Actions variables (not secrets) to every owned repo.
DISTRIBUTE_VARIABLES = (
    "LLM_API_KEY",
    "LLM_API_BASE",
    "LLM_MODEL",
)
WORKFLOW_VARS_BEGIN = "# BEGIN DISTRIBUTE_VARIABLES_ENV"
WORKFLOW_VARS_END = "# END DISTRIBUTE_VARIABLES_ENV"
SECRETS_TO_PURGE = {
    "ANTHROPIC_VERTEX_PROJECT_ID",
    "CLAUDE_CODE_USE_VERTEX",
    "CODACY_PROJECT_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS_JSON",
    "CURSOR_API_KEY",
    "LLM_API_KEY",
    "LLM_API_BASE",
    "LLM_MODEL",
    "OPENCODE_MODEL",
}
# Codacy account API token for all repos (hub may store as CODACY_PROJECT_TOKEN).
CODACY_DISTRIBUTE_SECRET = "CODACY_API_TOKEN"
CODACY_HUB_SECRET_NAMES = ("CODACY_PROJECT_TOKEN", CODACY_DISTRIBUTE_SECRET)
HUB_ONLY_SECRETS = {
    "ACTIONS_RUNNER_DEBUG",
    "ACTIONS_STEP_DEBUG",
    "CODACY_PROJECT_TOKEN",
    "PUBLISH",
}
# Also written to each repo's Dependabot secrets so scans on Dependabot PRs work.
DEPENDABOT_SECRETS = ("CODACY_API_TOKEN", "SONAR_TOKEN")
DEPENDABOT_HASH_VAR_NAME = "DEPENDABOT_SECRETS_HASH"
DISTRIBUTE_SECRETS_WORKFLOW = Path(".github/workflows/distribute-secrets.yaml")
WORKFLOW_ENV_BEGIN = "# BEGIN DISTRIBUTE_SECRETS_ENV"
WORKFLOW_ENV_END = "# END DISTRIBUTE_SECRETS_ENV"

# Headers for GitHub API requests
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# Rate limit delay between API calls (seconds)
API_DELAY = 1
GH_CLI_DELAY = 1.5
HTTP_TIMEOUT = 60

# Reserve buffer to avoid hitting the limit
RATE_LIMIT_RESERVE = 100


def hash_value(value):
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def compute_per_secret_hashes(secrets):
    return {key: hash_value(value) for key, value in secrets.items() if value is not None}


def check_rate_limit():
    response = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=HTTP_TIMEOUT)
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
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        if response.status_code in (403, 429):
            retry_after = int(response.headers.get("Retry-After", 60))
            print(f"  Rate limited, waiting {retry_after}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_after)
            continue
        return response
    return response


def authenticate_gh():
    os.environ.pop("GITHUB_TOKEN", None)

    token = f"{GITHUB_TOKEN}"
    with open(".githubtoken", "w", encoding="utf-8") as f:
        f.write(token)

    subprocess.run(
        ["gh", "auth", "login", "--with-token"],
        input=token,
        text=True,
        check=True,
    )

    os.remove(".githubtoken")


def set_secret(repo_name, secret, value, app="actions"):
    cmd = [
        "gh",
        "secret",
        "set",
        secret,
        "--app",
        app,
        "-R",
        f"{GITHUB_USER}/{repo_name}",
        "-b",
        value,
    ]

    try:
        time.sleep(GH_CLI_DELAY)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"    Set {app} secret {secret}")
    except subprocess.CalledProcessError as e:
        print(f"    Failed to set {app} secret {secret}: {e.stderr}")


def get_remote_hashes(repo_name, var_name=HASH_VAR_NAME):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/variables/{var_name}"
    response = rate_limited_get(url)
    if response.status_code == 200:
        try:
            return json.loads(response.json().get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def set_repo_variable(repo_name, name, value):
    repo_full = f"{GITHUB_USER}/{repo_name}"
    url = f"https://api.github.com/repos/{repo_full}/actions/variables/{name}"
    time.sleep(API_DELAY)
    response = requests.patch(url, headers=headers, json={"value": value}, timeout=HTTP_TIMEOUT)
    if response.status_code == 204:
        print("    Updated hash variable")
        return

    url = f"https://api.github.com/repos/{repo_full}/actions/variables"
    time.sleep(API_DELAY)
    response = requests.post(url, headers=headers, json={"name": name, "value": value}, timeout=HTTP_TIMEOUT)
    if response.status_code == 201:
        print("    Created hash variable")
    else:
        print(f"    Failed to set variable {name}: {response.status_code} {response.text}")


def delete_repo_variable(repo_name, name):
    repo_full = f"{GITHUB_USER}/{repo_name}"
    url = f"https://api.github.com/repos/{repo_full}/actions/variables/{name}"
    time.sleep(API_DELAY)
    response = requests.delete(url, headers=headers, timeout=HTTP_TIMEOUT)
    if response.status_code == 204:
        print(f"    Deleted variable {name}")
    elif response.status_code != 404:
        print(f"    Failed to delete variable {name}: {response.status_code} {response.text}")


def get_hub_variable_value(name):
    url = f"https://api.github.com/repos/{GITHUB_USER}/dmzoneill/actions/variables/{name}"
    response = rate_limited_get(url)
    if response.status_code == 200:
        return response.json().get("value")
    return None


def get_remote_variable_hashes(repo_name):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/variables/{VARIABLES_HASH_VAR_NAME}"
    response = rate_limited_get(url)
    if response.status_code == 200:
        try:
            return json.loads(response.json().get("value", "{}"))
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def sync_repo_variables(repo_name, variables, current_hashes, remote_hashes):
    changed = [key for key, h in current_hashes.items() if remote_hashes.get(key) != h]
    removed = [k for k in remote_hashes if k not in current_hashes]

    if not changed and not removed:
        print("  All variables up to date, skipping")
        return

    if changed:
        print(f"  {len(changed)} variable(s) changed: {', '.join(changed)}")
        for key in changed:
            set_repo_variable(repo_name, key, variables[key])

    if removed:
        print(f"  {len(removed)} variable(s) removed: {', '.join(removed)}")
        for key in removed:
            delete_repo_variable(repo_name, key)

    set_repo_variable(repo_name, VARIABLES_HASH_VAR_NAME, json.dumps(current_hashes))


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
    changed = sum(1 for k, v in current_hashes.items() if remote_hashes.get(k) != v)
    removed = sum(1 for k in remote_hashes if k not in current_hashes)
    if not changed and not removed:
        # 1 (fetch existing secrets) + some potential deprecated deletes
        return 7
    # changed*2 (gh secret set) + removed (delete) + 2 (set var) + 1 (fetch) + buffer
    # +6 covers Dependabot secrets (hash fetch, up to 2 sets, hash write)
    return changed * 2 + removed + 11


def cleanup_deprecated_secrets(repo_name, existing_secrets, current_names):
    to_delete = [
        s for s in existing_secrets if s in SECRETS_TO_PURGE or (s not in current_names and s != HASH_VAR_NAME)
    ]
    if to_delete:
        print(f"  Cleaning up {len(to_delete)} deprecated secret(s): {', '.join(to_delete)}")
        for key in to_delete:
            delete_secret(repo_name, key)
    return to_delete


def fetch_existing_secret_names(repo_name):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/secrets"
    response = rate_limited_get(url)
    if response.status_code == 200:
        return {s["name"] for s in response.json().get("secrets", [])}
    return set()


def sync_repo_secrets(repo_name, secrets, current_hashes, remote_hashes):
    changed = [key for key, h in current_hashes.items() if remote_hashes.get(key) != h]
    removed = [k for k in remote_hashes if k not in current_hashes]

    existing = fetch_existing_secret_names(repo_name)
    deprecated = cleanup_deprecated_secrets(repo_name, existing, set(secrets.keys()))

    if not changed and not removed and not deprecated:
        print("  All secrets up to date, skipping")
        return

    if changed:
        print(f"  {len(changed)} secret(s) changed: {', '.join(changed)}")
        for key in changed:
            set_secret(repo_name, key, secrets[key])

    if removed:
        print(f"  {len(removed)} secret(s) removed: {', '.join(removed)}")
        for key in removed:
            delete_secret(repo_name, key)

    set_repo_variable(repo_name, HASH_VAR_NAME, json.dumps(current_hashes))


def sync_dependabot_secrets(repo_name, secrets):
    """Mirror DEPENDABOT_SECRETS into the repo's Dependabot secrets (hash-tracked)."""
    wanted = {name: secrets[name] for name in DEPENDABOT_SECRETS if secrets.get(name) is not None}
    current_hashes = compute_per_secret_hashes(wanted)
    remote_hashes = get_remote_hashes(repo_name, DEPENDABOT_HASH_VAR_NAME)
    changed = [key for key, h in current_hashes.items() if remote_hashes.get(key) != h]
    if not changed:
        print("  Dependabot secrets up to date, skipping")
        return
    print(f"  {len(changed)} Dependabot secret(s) changed: {', '.join(changed)}")
    for key in changed:
        set_secret(repo_name, key, wanted[key], app="dependabot")
    set_repo_variable(repo_name, DEPENDABOT_HASH_VAR_NAME, json.dumps(current_hashes))


def get_hub_secret_names():
    url = f"https://api.github.com/repos/{GITHUB_USER}/dmzoneill/actions/secrets"
    names = set()
    while url:
        response = rate_limited_get(url)
        if response.status_code != 200:
            print(f"Failed to fetch hub secret names: {response.status_code}")
            break
        data = response.json()
        names.update(s["name"] for s in data.get("secrets", []))
        url = response.links.get("next", {}).get("url")
    return names


def get_hub_codacy_token_source(hub_names):
    if CODACY_DISTRIBUTE_SECRET in hub_names:
        return CODACY_DISTRIBUTE_SECRET
    if "CODACY_PROJECT_TOKEN" in hub_names:
        return "CODACY_PROJECT_TOKEN"
    return None


def get_secret_names():
    hub_names = get_hub_secret_names()
    names = [
        name
        for name in hub_names
        if (name != HASH_VAR_NAME and name not in SECRETS_TO_PURGE and name not in HUB_ONLY_SECRETS)
        and name not in DISTRIBUTE_VARIABLES
    ]
    if get_hub_codacy_token_source(hub_names) and CODACY_DISTRIBUTE_SECRET not in names:
        names.append(CODACY_DISTRIBUTE_SECRET)
    return sorted(names)


def get_repositories():
    page = 1
    repos = []
    while True:
        response = rate_limited_get(f"{REPO_LIST_URL}&page={page}")
        if response.status_code == 200:
            repos_data = response.json()
            if not repos_data:
                break
            repos.extend([repo["name"] for repo in repos_data if repo["name"] != "dmzoneill"])
            page += 1
        else:
            print(f"Failed to fetch repositories, status code: {response.status_code}")
            break
    return repos


def build_workflow_env_lines(secret_names, hub_names=None):
    """YAML env entries for distribute-secrets workflow (secrets + whitelisted variables)."""
    hub_names = hub_names or get_hub_secret_names()
    codacy_source = get_hub_codacy_token_source(hub_names)
    lines = [
        f"          {WORKFLOW_ENV_BEGIN}",
        "          GITHUB_TOKEN: ${{ secrets.PROFILE_HOOK }}",
    ]
    for name in sorted(secret_names):
        if name == CODACY_DISTRIBUTE_SECRET and codacy_source:
            lines.append(f"          {CODACY_DISTRIBUTE_SECRET}: ${{{{ secrets.{codacy_source} }}}}")
        else:
            lines.append(f"          {name}: ${{{{ secrets.{name} }}}}")
    lines.append(f"          {WORKFLOW_ENV_END}")
    lines.append(f"          {WORKFLOW_VARS_BEGIN}")
    for name in DISTRIBUTE_VARIABLES:
        lines.append(f"          {name}: ${{{{ vars.{name} }}}}")
    lines.append(f"          {WORKFLOW_VARS_END}")
    return lines


def parse_workflow_env_secret_names(workflow_text):
    if WORKFLOW_ENV_BEGIN not in workflow_text or WORKFLOW_ENV_END not in workflow_text:
        return None
    start = workflow_text.index(WORKFLOW_ENV_BEGIN)
    end = workflow_text.index(WORKFLOW_ENV_END, start)
    block = workflow_text[start:end]
    names = set()
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split(":", 1)[0].strip()
        if key != "GITHUB_TOKEN":
            names.add(key)
    return names


def parse_workflow_env_variable_names(workflow_text):
    if WORKFLOW_VARS_BEGIN not in workflow_text or WORKFLOW_VARS_END not in workflow_text:
        return None
    start = workflow_text.index(WORKFLOW_VARS_BEGIN)
    end = workflow_text.index(WORKFLOW_VARS_END, start)
    block = workflow_text[start:end]
    names = set()
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split(":", 1)[0].strip()
        names.add(key)
    return names


def _report_env_drift(missing, extra, missing_vars, extra_vars):
    if missing:
        print(f"Workflow missing env for: {', '.join(missing)}")
    if extra:
        print(f"Workflow has stale env entries: {', '.join(extra)}")
    if missing_vars:
        print(f"Workflow missing variables env for: {', '.join(missing_vars)}")
    if extra_vars:
        print(f"Workflow has stale variables env entries: {', '.join(extra_vars)}")
    print("Run: python3 setup.py --sync-workflow")


def sync_distribute_workflow(check_only=False):  # pylint: disable=too-many-return-statements
    secret_names = get_secret_names()
    if not secret_names:
        print("No distributable secrets found on dmzoneill repo")
        return 1

    workflow_path = DISTRIBUTE_SECRETS_WORKFLOW
    if not workflow_path.is_file():
        print(f"Missing workflow file: {workflow_path}")
        return 1

    workflow_text = workflow_path.read_text(encoding="utf-8")
    expected_names = set(secret_names)
    current_names = parse_workflow_env_secret_names(workflow_text)
    current_var_names = parse_workflow_env_variable_names(workflow_text)
    expected_var_names = set(DISTRIBUTE_VARIABLES)

    if check_only and (current_names is None or current_var_names is None):
        print(f"Workflow env markers not found in {workflow_path}; run: python3 setup.py --sync-workflow")
        return 1

    missing, extra = _env_diff(expected_names, current_names)
    missing_vars, extra_vars = _env_diff(expected_var_names, current_var_names)
    if not missing and not extra and not missing_vars and not extra_vars:
        print(f"Workflow env matches {len(expected_names)} repo secrets and {len(expected_var_names)} repo variables")
        return 0

    if check_only:
        _report_env_drift(missing, extra, missing_vars, extra_vars)
        return 1

    env_block = "\n".join(build_workflow_env_lines(secret_names, get_hub_secret_names()))
    pattern = re.compile(
        r"([ \t]+env:\n)(?:[ \t]+\S.*\n)+?([ \t]+run: python3 setup\.py[ \t]*\n)",
        re.MULTILINE,
    )
    if not pattern.search(workflow_text):
        print(f"Could not locate env block in {workflow_path}")
        return 1

    updated = pattern.sub(rf"\1{env_block}\n\2", workflow_text, count=1)
    workflow_path.write_text(updated, encoding="utf-8")
    print(
        f"Updated {workflow_path} with {len(secret_names)} secrets"
        + (f" (added {', '.join(missing)})" if missing else "")
        + (f" (removed {', '.join(extra)})" if extra else "")
    )
    return 0


def load_variables():
    variables = {}
    for name in DISTRIBUTE_VARIABLES:
        value = os.getenv(name)
        if value is None:
            value = get_hub_variable_value(name)
        variables[name] = value

    missing_variables = [name for name, value in variables.items() if value is None]
    if missing_variables:
        print(f"Skipping unset variables: {', '.join(missing_variables)}")

    variable_hashes = compute_per_secret_hashes(variables)
    print(f"Computed hashes for {len(variable_hashes)} variables")
    return variables, variable_hashes


def _env_diff(expected, current):
    if current is None:
        return [], []
    return sorted(expected - current), sorted(current - expected)


def main():
    secret_names = get_secret_names()
    if not secret_names:
        print("No secrets found on dmzoneill repo, aborting")
        return

    print(f"Found {len(secret_names)} secrets on dmzoneill repo")
    secrets = {name: os.getenv(name) for name in secret_names}
    if CODACY_DISTRIBUTE_SECRET in secrets and secrets[CODACY_DISTRIBUTE_SECRET] is None:
        secrets[CODACY_DISTRIBUTE_SECRET] = os.getenv("CODACY_PROJECT_TOKEN")

    missing_secrets = [secret for secret, value in secrets.items() if value is None]
    if missing_secrets:
        print(f"Skipping unset secrets: {', '.join(missing_secrets)}")

    current_hashes = compute_per_secret_hashes(secrets)
    print(f"Computed hashes for {len(current_hashes)} secrets")

    variables, variable_hashes = load_variables()

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
            print(f"\nSkipping {repo}: {remaining} calls left, need {cost}+{RATE_LIMIT_RESERVE}")
            skipped += 1
            continue

        print(f"\nSyncing secrets for: {repo} (est. cost: {cost})")
        sync_repo_secrets(repo, secrets, current_hashes, remote_hashes)
        sync_dependabot_secrets(repo, secrets)
        remote_variable_hashes = get_remote_variable_hashes(repo)
        sync_repo_variables(repo, variables, variable_hashes, remote_variable_hashes)
        synced += 1

    print(f"\nDone: synced {synced} repos")
    if skipped:
        print(f"Deferred {skipped} repos due to rate limit (will resume next run)")


if __name__ == "__main__":
    if "--sync-workflow" in sys.argv:
        raise SystemExit(sync_distribute_workflow(check_only=False))
    if "--check-workflow" in sys.argv:
        raise SystemExit(sync_distribute_workflow(check_only=True))
    main()
