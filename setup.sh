#!/bin/bash

COUNTER=1
for X in `curl 'https://api.github.com/users/dmzoneill/repos?per_page=100' | jq -r '.[] | .ssh_url'`; do
  printf "%d\n" $COUNTER
  let COUNTER=COUNTER+1
  name=$(echo $X | awk -F'/' '{print $2}' | sed 's/\.git//')
  exists=$(curl -s -o /dev/null -w "%{http_code}" https://github.com/dmzoneill/$name/blob/master/.github/workflows/main.yml)
  
  [[ "$exists" == "404" ]] && git clone https://dmzoneill:${{ secrets.PROFILE_HOOK }}@github.com/dmzoneill/$name.git $X;
  [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/"
  
  mkdir -vp "$name/.github/workflows/"
  cp main.yml "$name/.github/workflows/"
  
  cd "$name"
  gh secret set profile_hook -r "dmzoneill/$name" -b "{{ secrets.PROFILE_HOOK }}"
  git config --global user.email "dmz.oneill@gmail.com"
  git config --global user.name "dmzoneill"
  git remote set-url origin https://dmzoneill:${{ secrets.PROFILE_HOOK }}@github.com/dmzoneill/$name.git
  git add -A
  git commit -a -m "add github action and setup secret"
  git pull --rebase
  git push 
  cd ..  
done