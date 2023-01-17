#!/bin/bash

user=dmzoneill
email=dmz.oneill@gmail.com

COUNTER=1
for X in `curl "https://api.github.com/users/$user/repos?per_page=100" | jq -r '.[] | .ssh_url'`; do
  printf "%d\n" $COUNTER  
  name=$(echo $X | awk -F'/' '{print $2}' | sed 's/\.git//')
  echo $name
  repo="https://github.com/$user/$name/blob/master/.github/workflows/main.yml"
  exists=$(curl -s -o /dev/null -w "%{http_code}" $repo)
  
  [[ "$exists" == "200" ]] && continue
  git_url="https://$user:${{ secrets.PROFILE_HOOK }}@github.com/$user/$name.git"
  git clone "$git_url";

  [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"
  
  mkdir -vp "$name/.github/workflows/"
  cp main.yml "$name/.github/workflows/"
  
  cd "$name"
  gh secret set profile_hook -r "$user/$name" -b "${{ secrets.PROFILE_HOOK }}"
  git config --global user.email "$email"
  git config --global user.name "$user"

  git remote set-url origin "$git_url"
  git add -A
  git commit -a -m "add github action and setup secret"
  git pull --rebase
  git push 
  cd .. 
  let COUNTER=COUNTER+1 
done