#!/bin/bash -x

user=dmzoneill
email=dmz.oneill@gmail.com
pass=$PROFILE_HOOK

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

page=1
while true; do
  echo "Page: $page"
  url="https://api.github.com/users/$user/repos?per_page=100&page=$page"
  echo "$url"
  processed=0
  for X in $(curl "$url" | jq -r '.[] | .ssh_url'); do   
    name=$(echo "$X" | awk -F'/' '{print $2}' | sed 's/\.git//')
    echo "$pass" > .githubtoken
    unset GITHUB_TOKEN
    gh auth login --with-token < .githubtoken
    export GITHUB_TOKEN=$(cat .githubtoken)
    rm .githubtoken    

    # Skip the main repository
    if [[ "$name" == "dmzoneill" ]]; then
      echo "Skipping repository $name"
      continue
    fi

    # Set secrets for each repository except 'dmzoneill'
    gh secret set GITHUB_TOKEN -r "$user/$name" -b "$GITHUB_TOKEN"
    gh secret set PROFILE_HOOK -r "$user/$name" -b "$PROFILE_HOOK"
    gh secret set ACTIONS_RUNNER_DEBUG -r "$user/$name" -b "$ACTIONS_RUNNER_DEBUG"
    gh secret set ACTIONS_STEP_DEBUG -r "$user/$name" -b "$ACTIONS_STEP_DEBUG"
    gh secret set AI_API_KEY -r "$user/$name" -b "$AI_API_KEY"
    gh secret set AI_MODEL -r "$user/$name" -b "$AI_MODEL"
    gh secret set DOCKER_TOKEN -r "$user/$name" -b "$DOCKER_TOKEN"
    gh secret set PUBLISH -r "$user/$name" -b "$PUBLISH"
    gh secret set PYPI_TOKEN -r "$user/$name" -b "$PYPI_TOKEN"
    gh secret set WORDPRESS_APPLICATION -r "$user/$name" -b "$WORDPRESS_APPLICATION"
    gh secret set WORDPRESS_PASSWORD -r "$user/$name" -b "$WORDPRESS_PASSWORD"
    gh secret set WORDPRESS_URL -r "$user/$name" -b "$WORDPRESS_URL"
    gh secret set WORDPRESS_USERNAME -r "$user/$name" -b "$WORDPRESS_USERNAME"

    action_file="https://github.com/$user/$name/blob/main/.github/workflows/main.yml?raw=true"
    exists=$(curl -L -s -o /tmp/last -w "%{http_code}" "$action_file")
    md5file=$(md5sum /tmp/last | awk '{print $1}')

    processed=$((processed+1))

    if [[ "$md5file" == "7cb66df6acac5c1c322e08e6d468a982" ]]; then
       exists="404"
    fi 
    
    [[ "$exists" != "404" ]] && echo "Skip action exists" && echo "$processed" && continue

    git_url=https://$user:$pass@github.com/$user/$name.git
    git clone "$git_url"

    [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"
    
    mkdir -vp "$name/.github/workflows/"
    cp -f main.yml "$name/.github/workflows/"
    
    (
      cd "$name" || exit 1
      git config --global user.email $email
      git config --global user.name $user

      git remote set-url origin "$git_url"
      git add -A
      git commit -a -m "add github action and setup secret"
      git pull --rebase
      git push 
    )
    echo "$processed"
  done

  if [ $processed -le 1 ]; then
    echo "Exited 0 processed"
    exit 0;
  fi

  page=$((page+1))
done
