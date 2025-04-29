#!/bin/bash -x

# Set user and email variables
user="dmzoneill"
email="dmz.oneill@gmail.com"
pass="$PROFILE_HOOK"

# Secrets
GITHUB_TOKEN="$GITHUB_TOKEN"
PROFILE_HOOK="$PROFILE_HOOK"
ACTIONS_RUNNER_DEBUG="$ACTIONS_RUNNER_DEBUG"
ACTIONS_STEP_DEBUG="$ACTIONS_STEP_DEBUG"
AI_API_KEY="$AI_API_KEY"
AI_MODEL="$AI_MODEL"
DOCKER_TOKEN="$DOCKER_TOKEN"
PUBLISH="$PUBLISH"
PYPI_TOKEN="$PYPI_TOKEN"
WORDPRESS_APPLICATION="$WORDPRESS_APPLICATION"
WORDPRESS_PASSWORD="$WORDPRESS_PASSWORD"
WORDPRESS_URL="$WORDPRESS_URL"
WORDPRESS_USERNAME="$WORDPRESS_USERNAME"

# Check GitHub authentication status
echo "Checking GitHub authentication status..."
gh auth status || { echo "GitHub authentication failed. Please login with 'gh auth login'."; exit 1; }

# Pagination variable for fetching multiple pages of repos
page=1
while true; do
  echo "Page: $page"
  url="https://api.github.com/users/$user/repos?per_page=100&page=$page"
  echo "Fetching URL: $url"
  processed=0

  # Fetch and iterate through repositories
  for X in $(curl -s "$url" | jq -r '.[] | .ssh_url'); do   
    name=$(echo "$X" | awk -F'/' '{print $2}' | sed 's/\.git//')
    echo "  Setting up repository: $name.."

    # Authentication setup
    echo "$pass" > .githubtoken
    unset GITHUB_TOKEN
    gh auth login --with-token < .githubtoken
    export GITHUB_TOKEN=$(cat .githubtoken)
    rm .githubtoken    

    # Check repository access
    echo "    Checking repository access for $user/$name..."
    gh repo view "$user/$name" || { echo "Failed to access repository $user/$name. Skipping."; continue; }

    # Skip the main repository
    if [[ "$name" == "dmzoneill" ]]; then
      echo "    Skipping repository $name"
      continue
    fi

    # Set up secrets
    echo "    Setting up secrets for $name.."
    secrets=("PROFILE_HOOK" "ACTIONS_RUNNER_DEBUG" "ACTIONS_STEP_DEBUG" "AI_API_KEY" "AI_MODEL" "DOCKER_TOKEN" "PUBLISH" "PYPI_TOKEN" "WORDPRESS_APPLICATION" "WORDPRESS_PASSWORD" "WORDPRESS_URL" "WORDPRESS_USERNAME")
    for secret in "${secrets[@]}"; do
      gh secret set "$secret" -r "$user/$name" -b "${!secret}" || { echo "Failed to set secret $secret for $name"; exit 1; }
    done

    # Check if the GitHub Actions file exists
    echo "    Checking GitHub Actions file for $name.."
    action_file="https://github.com/$user/$name/blob/main/.github/workflows/main.yml?raw=true"
    exists=$(curl -L -s -o /tmp/last -w "%{http_code}" "$action_file")
    md5file=$(md5sum /tmp/last | awk '{print $1}')

    # If the file is unchanged, skip
    if [[ "$md5file" == "7cb66df6acac5c1c322e08e6d468a982" ]]; then
       exists="404"
    fi 
    
    if [[ "$exists" != "404" ]]; then
      echo "    Actions config exists"
      processed=$((processed+1))
      continue
    fi

    # If Actions config doesn't exist, clone and set up
    echo "    Cloning $name.."
    git_url=https://$user:$pass@github.com/$user/$name.git
    git clone "$git_url"

    [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"

    echo "    Committing actions and license to $name.."
    mkdir -vp "$name/.github/workflows/"
    cp -f main.yml "$name/.github/workflows/"
    
    (
      cd "$name" || exit 1
      git config --global user.email "$email"
      git config --global user.name "$user"

      git remote set-url origin "$git_url"
      git add -A
      git commit -a -m "add github action and setup secret"
      git pull --rebase
      git push 
    )
    echo "    Repository $name updated"
  done

  # Exit if no new repositories were processed
  if [ $processed -le 1 ]; then
    echo "No new repositories processed, exiting.."
    exit 0
  fi

  # Increment page number for pagination
  page=$((page+1))
done

echo "All repositories processed."
