#!/bin/bash -x

user=dmzoneill
email=dmz.oneill@gmail.com
pass=$PROFILE_HOOK

for X in $(curl "https://api.github.com/users/$user/repos?per_page=100" | jq -r '.[] | .ssh_url'); do
  name=$(echo "$X" | awk -F'/' '{print $2}' | sed 's/\.git//')
  echo "$name"
  action_file="https://github.com/$user/$name/blob/master/.github/workflows/main.yml"
  exists=$(curl -s -o /dev/null -w "%{http_code}" "$action_file")
  
  [[ "$exists" == "200" ]] && echo "Skip action eixsts" && continue

  git_url=https://$user:$pass@github.com/$user/$name.git
  git clone "$git_url"

  [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"
  
  mkdir -vp "$name/.github/workflows/"
  cp main.yml "$name/.github/workflows/"
  
  (
    cd $name || exit 1
    gh secret set profile_hook -r "$user/$name" -b "$pass"
    git config --global user.email $email
    git config --global user.name $user

    git remote set-url origin "$git_url"
    git add -A
    git commit -a -m "add github action and setup secret"
    git pull --rebase
    git push 
  )
done