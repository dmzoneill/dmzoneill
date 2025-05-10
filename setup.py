import os
import requests
import subprocess

# Constants
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USER = "dmzoneill"
REPO_LIST_URL = f"https://api.github.com/user/repos?affiliation=owner&per_page=100"
SECRETS = [
    "PROFILE_HOOK",
    "AI_API_KEY",
    "AI_MODEL",
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
    "REDIS_PASSWORD"
]

# Headers for GitHub API requests
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# Function to fetch existing secrets for a repository
# Function to fetch existing secrets for a repository
def fetch_existing_secrets(repo_name):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/secrets"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        # Ensure the response is parsed as JSON
        secrets = response.json()
        # Return a set of secret names
        return {secret["name"] for secret in secrets['secrets']}  # This assumes the response is a list of secrets with 'name' as a key
    else:
        print(f"Failed to fetch existing secrets for {repo_name}, status code: {response.status_code}")
        return set()

# Function to fetch secrets from the environment
def fetch_secrets_from_env():
    secrets = {}
    missing_secrets = []

    for secret in SECRETS:
        secret_value = os.getenv(secret)

        if secret_value:
            secrets[secret] = secret_value
        else:
            missing_secrets.append(secret)
            secrets[secret] = None

    return secrets, missing_secrets


# Function to authenticate using GitHub CLI
def authenticate_gh():
    # Unset the GITHUB_TOKEN environment variable to prevent conflict
    os.environ.pop("GITHUB_TOKEN", None)

    # Create a temporary file for the token
    with open(".githubtoken", "w") as f:
        f.write(f"{GITHUB_TOKEN}")

    # Authenticate using the GitHub CLI
    subprocess.run(["gh", "auth", "login", "--with-token"], input=open(".githubtoken").read(), text=True, check=True)

    # Clean up the token file
    os.remove(".githubtoken")


def set_secrets_with_gh(repo_name, secrets):
    # Fetch existing secrets for the repository
    existing_secrets = fetch_existing_secrets(repo_name)
    
    # Authenticate with GitHub CLI
    authenticate_gh()
    
    for secret, value in secrets.items():
        if value is None:
            print(f"  Skipping unset secret {secret} for {repo_name}")
            continue
        
        # Skip if the secret already exists
        if secret in existing_secrets:
            print(f"  Secret {secret} already exists in repository {repo_name}. Skipping...")
            continue
        
        # Use GitHub CLI to set the secret
        print(f"\n  Setting secret {secret} for repository {repo_name} using GitHub CLI")

        cmd = [
            "gh", "secret", "set", secret,
            "-R", f"{GITHUB_USER}/{repo_name}",
            "-b", value
        ]

        print(f"    Running: {' '.join(cmd)}")

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"      ✅ Successfully set secret {secret} for repository {repo_name}\n")
        except subprocess.CalledProcessError as e:
            print(f"  ❌ Failed to set secret {secret} for {repo_name}")
            print(f"  STDERR: {e.stderr}")
            print(f"  STDOUT: {e.stdout}")

# Function to get all repositories
def get_repositories():
    page = 1
    repos = []
    while True:
        response = requests.get(f"{REPO_LIST_URL}&page={page}", headers=headers)
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


def main():
    # Fetch secrets from environment
    secrets = {secret: os.getenv(secret) for secret in SECRETS}
    
    # Check for missing secrets
    missing_secrets = [secret for secret, value in secrets.items() if value is None]
    if missing_secrets:
        print(f"Missing secrets: {', '.join(missing_secrets)}")
        return

    # Fetch repositories to update
    repos = get_repositories()

    # Set secrets for each repository
    for repo in repos:
        if repo == "dmzoneill":
            continue
        print(f"\nSetting secrets for repository: {repo}")
        set_secrets_with_gh(repo, secrets)


if __name__ == "__main__":
    main()
