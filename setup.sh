#!/bin/bash

user=dmzoneill
email=dmz.oneill@gmail.com

COUNTER=1
for X in `curl "https://api.github.com/users/$user/repos?per_page=100" | jq -r '.[] | .ssh_url'`; do
  printf "%d\n" $COUNTER
  let COUNTER=COUNTER+1
  name=$(echo $X | awk -F'/' '{print $2}' | sed 's/\.git//')
  exists=$(curl -s -o /dev/null -w "%{http_code}" https://github.com/$user/$name/blob/master/.github/workflows/main.yml)
  
  [[ "$exists" == "200" ]] && continue
  git clone https://$user:${{ secrets.PROFILE_HOOK }}@github.com/$user/$name.git $X;

  [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"
  
  mkdir -vp "$name/.github/workflows/"
  cp main.yml "$name/.github/workflows/"
  
  cd "$name"
  gh secret set profile_hook -r "$user/$name" -b "{{ secrets.PROFILE_HOOK }}"
  git config --global user.email "$email"
  git config --global user.name "$user"

  url="https://$user:${{ secrets.PROFILE_HOOK }}@github.com/$user/${name}.git"

  git remote set-url origin $url
  git add -A
  git commit -a -m "add github action and setup secret"
  git pull --rebase
  git push 
  cd ..  
done