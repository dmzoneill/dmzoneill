#!/bin/bash -x

user=dmzoneill
email=dmz.oneill@gmail.com
pass=$PROFILE_HOOK

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

    # Check if main.yml exists
    main_url="https://raw.githubusercontent.com/$user/$name/main/.github/workflows/main.yml"
    curl -s -L -o /tmp/main_check "$main_url"
    main_md5=$(md5sum /tmp/main_check | awk '{print $1}')
    if [[ "$main_md5" == "7cb66df6acac5c1c322e08e6d468a982" || ! -s /tmp/main_check ]]; then
      main_status="404"
    else
      main_status="200"
    fi

    # Check if ai-responder.yml exists
    ai_url="https://raw.githubusercontent.com/$user/$name/main/.github/workflows/ai-responder.yml"
    curl -s -L -o /tmp/ai_check "$ai_url"
    ai_md5=$(md5sum /tmp/ai_check | awk '{print $1}')
    if [[ "$ai_md5" == "7cb66df6acac5c1c322e08e6d468a982" || "$ai_md5" == "d41d8cd98f00b204e9800998ecf8427e" || ! -s /tmp/ai_check ]]; then
      ai_status="404"
    else
      ai_status="200"
    fi

    echo "$name: main_status=$main_status, ai_status=$ai_status"

    # Only proceed if either file is missing
    if [[ "$main_status" != "404" && "$ai_status" != "404" ]]; then
      echo "Skip: both actions exist in $name"
      continue
    fi

    processed=$((processed+1))
    git_url="https://$user:$pass@github.com/$user/$name.git"
    git clone "$git_url"

    [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"

    mkdir -vp "$name/.github/workflows/"
    [ "$main_status" == "404" ] && cp -f main.yml "$name/.github/workflows/"
    [ "$ai_status" == "404" ] && cp -f ai-responder.yml "$name/.github/workflows/"
    
    (
      cd "$name" || exit 1
      gh secret set profile_hook -r "$user/$name" -b "$pass"
      git config --global user.email "$email"
      git config --global user.name "$user"

      git remote set-url origin "$git_url"
      git add -A
      git commit -a -m "Add missing GitHub Actions workflows"
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
