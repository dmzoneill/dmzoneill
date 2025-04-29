import os
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from base64 import b64encode

# Constants
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USER = "dmzoneill"
REPO_LIST_URL = f"https://api.github.com/users/{GITHUB_USER}/repos?per_page=100"
SECRETS = [
    "PROFILE_HOOK", "ACTIONS_RUNNER_DEBUG", "ACTIONS_STEP_DEBUG", "AI_API_KEY", "AI_MODEL", 
    "DOCKER_TOKEN", "PUBLISH", "PYPI_TOKEN", "WORDPRESS_APPLICATION", "WORDPRESS_PASSWORD", 
    "WORDPRESS_URL", "WORDPRESS_USERNAME"
]

# Headers for GitHub API requests
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# Function to fetch public key for encrypting secrets
def fetch_public_key(repo_name):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/secrets/public-key"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch public key for {repo_name}, status code: {response.status_code}")
        return None

# Function to encrypt the secret value using the public key
def encrypt_secret(public_key, secret_value):
    public_key_pem = serialization.load_pem_public_key(
        public_key.encode(), backend=default_backend()
    )
    encrypted_value = public_key_pem.encrypt(
        secret_value.encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return b64encode(encrypted_value).decode()

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

# Function to print secrets and check for unset ones
def print_secrets(secrets, missing_secrets):
    print("Secrets in environment:")
    
    for secret, secret_value in secrets.items():
        if secret_value:
            print(f"{secret}: SET")
        else:
            print(f"{secret}: UNSET")

    if missing_secrets:
        print("\nMissing Secrets (not set in environment):")
        for missing_secret in missing_secrets:
            print(f"- {missing_secret}")

# Function to set secrets in repositories
def set_secrets_for_repo(repo_name, secrets):
    public_key_data = fetch_public_key(repo_name)
    if not public_key_data:
        print(f"Skipping {repo_name} due to failure in fetching public key")
        return

    public_key = public_key_data["key"]
    for secret, value in secrets.items():
        if value is None:
            print(f"Skipping unset secret {secret} for {repo_name}")
            continue
        
        encrypted_value = encrypt_secret(public_key, value)
        url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/actions/secrets/{secret}"
        payload = {
            "encrypted_value": encrypted_value,
            "key_id": public_key_data["key_id"]
        }
        response = requests.put(url, headers=headers, json=payload)
        if response.status_code == 201:
            print(f"Successfully set secret {secret} for repository {repo_name}")
        else:
            print(f"Failed to set secret {secret} for repository {repo_name}, status code: {response.status_code}")

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

# Main function to fetch and print secrets, check missing ones, and update repositories
def main():
    # Fetch secrets from environment
    secrets, missing_secrets = fetch_secrets_from_env()
    
    # Print secrets and check for missing ones
    print_secrets(secrets, missing_secrets)

    # If there are missing secrets, abort the operation
    if missing_secrets:
        print("\nSome secrets are missing. Please set them in the environment.")
        return

    print("Proceeding with the repository update...")

    # Fetch repositories to update
    repos = get_repositories()

    for repo in repos:
        if repo == "dmzoneill":
            continue
        print(f"Setting secrets for repository: {repo}")
        set_secrets_for_repo(repo, secrets)

if __name__ == "__main__":
    main()
