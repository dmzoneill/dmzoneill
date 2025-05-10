#!/bin/bash -x

user=dmzoneill
email=dmz.oneill@gmail.com
pass=$PROFILE_HOOK

# Local reference md5sums
local_main_md5=$(md5sum main.yml | awk '{print $1}')
local_ai_md5=$(md5sum ai-responder.yml | awk '{print $1}')

page=1
while true; do
  echo "Page: $page"
  url="https://api.github.com/users/$user/repos?per_page=100&page=$page"
  echo "$url"
  processed=0

  for X in $(curl -s "$url" | jq -r '.[] | .ssh_url'); do   
    name=$(echo "$X" | awk -F'/' '{print $2}' | sed 's/\.git//')
    echo "Checking repo: $name"

    echo "$pass" > .githubtoken
    unset GITHUB_TOKEN
    gh auth login --with-token < .githubtoken
    export GITHUB_TOKEN=$(cat .githubtoken)
    rm -f .githubtoken    

    gh secret set profile_hook -r "$user/$name" -b "$pass"
    [[ "$name" == "dmzoneill" ]] && continue

    # === Check main.yml
    main_url="https://raw.githubusercontent.com/$user/$name/main/.github/workflows/main.yml"
    curl -s -L -o /tmp/main_check "$main_url"
    main_md5=$(md5sum /tmp/main_check 2>/dev/null | awk '{print $1}')
    if [[ ! -s /tmp/main_check || "$main_md5" == "7cb66df6acac5c1c322e08e6d468a982" ]]; then
      main_status="missing"
    elif grep -q "^name:" /tmp/main_check; then
      main_status="present"
    else
      main_status="corrupt"
    fi

    # === Check ai-responder.yml
    ai_url="https://raw.githubusercontent.com/$user/$name/main/.github/workflows/ai-responder.yml"
    curl -s -L -o /tmp/ai_check "$ai_url"
    ai_md5=$(md5sum /tmp/ai_check 2>/dev/null | awk '{print $1}')
    if [[ ! -s /tmp/ai_check || "$ai_md5" == "49eb909a86fe4c14013b3a0478ec0a0f" ]]; then
      ai_status="missing"
    elif grep -q "^name:" /tmp/ai_check; then
      ai_status="present"
    else
      ai_status="corrupt"
    fi

    echo "$name: main_status=$main_status, main_md5=$main_md5, local_main_md5=$local_main_md5"
    echo "$name: ai_status=$ai_status, ai_md5=$ai_md5, local_ai_md5=$local_ai_md5"

    skip_main="false"
    skip_ai="false"

    [[ "$main_status" == "present" && "$main_md5" == "$local_main_md5" ]] && skip_main="true"
    [[ "$ai_status" == "present" && "$ai_md5" == "$local_ai_md5" ]] && skip_ai="true"

    if [[ "$skip_main" == "true" && "$skip_ai" == "true" ]]; then
      echo "Skip: both files match in $name"
      continue
    fi

    processed=$((processed+1))
    git_url="https://$user:$pass@github.com/$user/$name.git"
    git clone "$git_url"

    [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"

    mkdir -vp "$name/.github/workflows/"
    [[ "$skip_main" != "true" ]] && cp -f main.yml "$name/.github/workflows/"
    [[ "$skip_ai" != "true" ]] && cp -f ai-responder.yml "$name/.github/workflows/"
    
    (
      cd "$name" || exit 1
      gh secret set profile_hook -r "$user/$name" -b "$pass"
      git config --global user.email "$email"
      git config --global user.name "$user"

      git remote set-url origin "$git_url"
      git add -A
      git commit -a -m "Add or update GitHub Actions workflows"
      git pull --rebase
      git push
    )
    echo "$processed"
  done

  if [ "$processed" -le 1 ]; then
    echo "Exited 0 processed"
    exit 0
  fi

  page=$((page+1))
done
