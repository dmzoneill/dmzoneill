#!/bin/bash -x

# Robust updater for adding workflows to repositories owned by $user.
# - Uses GitHub API pagination and Link header detection
# - Authenticates once if PROFILE_HOOK provided
# - Filters to only repos owned by $user (even when using /user/repos)
# - Clones into temporary per-repo directories to avoid name collisions
# - Sets secret only when possible; skips repos without admin rights

user=dmzoneill
email=dmz.oneill@gmail.com
pass=${PROFILE_HOOK:-}
per_page=100

# Local reference md5sums (only if files exist in this repo)
if [ -f main.yml ]; then
  local_main_md5=$(md5sum main.yml | awk '{print $1}')
else
  local_main_md5=""
fi

if [ -f ai-responder.yml ]; then
  local_ai_md5=$(md5sum ai-responder.yml | awk '{print $1}')
else
  local_ai_md5=""
fi

# Authenticate once (so gh and API requests can use the token)
if [ -n "$pass" ]; then
  echo "$pass" > .githubtoken
  unset GITHUB_TOKEN
  if ! gh auth login --with-token < .githubtoken; then
    echo "gh auth login failed"
    rm -f .githubtoken
    exit 1
  fi
  export GITHUB_TOKEN="$pass"
  rm -f .githubtoken
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

clone_base="$tmpdir/clones"
mkdir -p "$clone_base"

# Determine current repo full name to skip (if running inside a git repo)
current_full=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  origin_url=$(git config --get remote.origin.url || echo "")
  case "$origin_url" in
    git@github.com:*/*) current_full=${origin_url#git@github.com:}; current_full=${current_full%.git} ;;
    https://github.com/*/*) current_full=${origin_url#https://github.com/}; current_full=${current_full%.git} ;;
    *) current_full="" ;;
  esac
fi

process_repo() {
  local repo_owner="$1"
  local repo_name="$2"
  local repo_clone_url="$3"
  local can_set_secrets="$4"
  local repo_full="$repo_owner/$repo_name"

  if [ -n "$current_full" ] && [ "$repo_full" = "$current_full" ]; then
    echo "Skipping current repository $repo_full"
    return
  fi

  if [ "$can_set_secrets" = "true" ] && [ -n "$pass" ]; then
    gh secret set profile_hook -r "$repo_full" -b "$pass" || echo "Failed to set secret for $repo_full"
  fi

  local main_url="https://raw.githubusercontent.com/$repo_owner/$repo_name/main/.github/workflows/main.yml"
  local main_status="missing"
  local main_md5=""
  if curl -s -f -L "$main_url" > /tmp/main_check 2>/dev/null; then
    if grep -q "^name:" /tmp/main_check; then
      main_status="present"
      main_md5=$(md5sum /tmp/main_check 2>/dev/null | awk '{print $1}')
    else
      main_status="corrupt"
    fi
  fi

  local ai_url="https://raw.githubusercontent.com/$repo_owner/$repo_name/main/.github/workflows/ai-responder.yml"
  local ai_status="missing"
  local ai_md5=""
  if curl -s -f -L "$ai_url" > /tmp/ai_check 2>/dev/null; then
    if grep -q "^name:" /tmp/ai_check; then
      ai_status="present"
      ai_md5=$(md5sum /tmp/ai_check 2>/dev/null | awk '{print $1}')
    else
      ai_status="corrupt"
    fi
  fi

  echo "$repo_full: main_status=$main_status, main_md5=$main_md5, local_main_md5=$local_main_md5"
  echo "$repo_full: ai_status=$ai_status, ai_md5=$ai_md5, local_ai_md5=$local_ai_md5"

  local skip_main="false"
  local skip_ai="false"
  [[ "$main_status" == "present" && "$main_md5" == "$local_main_md5" ]] && skip_main="true"
  [[ "$ai_status" == "present" && "$ai_md5" == "$local_ai_md5" ]] && skip_ai="true"
  if [[ "$skip_main" == "true" && "$skip_ai" == "true" ]]; then
    echo "Skip: both files already match in $repo_full"
    return
  fi

  local target_dir="$clone_base/$repo_owner-$repo_name"
  rm -rf "$target_dir"
  if ! git clone --depth 1 "$repo_clone_url" "$target_dir"; then
    echo "Failed to clone $repo_clone_url into $target_dir"
    return
  fi

  if [ -f LICENSE ] && [ ! -f "$target_dir/LICENSE" ]; then
    cp -f LICENSE "$target_dir/"
  fi
  mkdir -p "$target_dir/.github/workflows/"
  if [[ "$skip_main" != "true" ]]; then
    cp -f main.yml "$target_dir/.github/workflows/"
  fi
  if [[ "$skip_ai" != "true" ]]; then
    cp -f ai-responder.yml "$target_dir/.github/workflows/"
  fi

  (
    cd "$target_dir" || exit 1

    if [ "$can_set_secrets" = "true" ] && [ -n "$pass" ]; then
      gh secret set profile_hook -r "$repo_full" -b "$pass" || echo "Failed to set secret inside $repo_full"
    fi

    git config user.email "$email"
    git config user.name "$user"

    if [ -n "$pass" ]; then
      push_url="https://$user:$pass@github.com/$repo_owner/$repo_name.git"
      git remote set-url origin "$push_url"
    fi

    git add -A
    if ! git diff --cached --quiet; then
      git commit -m "Add or update GitHub Actions workflows" || echo "git commit had no changes or failed"
      git pull --rebase || echo "git pull --rebase failed in $repo_full"
      git push || echo "git push failed in $repo_full"
    else
      echo "No changes to commit in $repo_full"
    fi
  )

  rm -rf "$target_dir"
}

page=1
while true; do
  echo "Page: $page"

  if [ -n "$GITHUB_TOKEN" ]; then
    api_base="https://api.github.com/user/repos"
  else
    api_base="https://api.github.com/users/$user/repos"
  fi
  url="$api_base?per_page=$per_page&page=$page"
  echo "$url"

  headers="$tmpdir/headers.$page"
  body="$tmpdir/body.$page"

  if [ -n "$GITHUB_TOKEN" ]; then
    curl -sS -H "Authorization: token $GITHUB_TOKEN" -D "$headers" -o "$body" "$url"
  else
    curl -sS -D "$headers" -o "$body" "$url"
  fi

  http_status=$(awk '/^HTTP\/[0-9.]+/ {code=$2} END {print code}' "$headers" 2>/dev/null || echo "")
  echo "HTTP status: $http_status"
  if [ "$http_status" != "200" ] && [ "$http_status" != "201" ]; then
    echo "GitHub API returned HTTP $http_status for page $page"
    echo "Response headers:"
    sed -n '1,200p' "$headers" || true
    echo "Response body:"
    sed -n '1,200p' "$body" || true
    exit 1
  fi

  repo_count=$(jq 'length' "$body" 2>/dev/null || echo 0)
  echo "Repos on this page (jq length): $repo_count"

  if [ "$repo_count" -eq 0 ]; then
    echo "No repos on page $page, exiting"
    break
  fi

  jq -r --arg OWNER "$user" '.[] | select(.owner.login == $OWNER) | [.owner.login, .name, .ssh_url, .clone_url, .permissions.admin] | @tsv' "$body" | \
  while IFS=$'\t' read -r repo_owner repo_name repo_ssh repo_clone_url repo_admin; do
    echo "Checking repo: $repo_owner/$repo_name (ssh_url: $repo_ssh, clone_url: $repo_clone_url, admin:$repo_admin)"

    can_set_secrets="false"
    if [ "$repo_admin" = "true" ]; then
      can_set_secrets="true"
    else
      echo "Note: token does not report admin for $repo_owner/$repo_name; skipping secret set"
    fi

    process_repo "$repo_owner" "$repo_name" "$repo_clone_url" "$can_set_secrets"
  done

  # Normalize Link header and pick last Link: line (handles redirects)
  echo "Response headers (raw):"
  sed -n '1,200p' "$headers" || true
  normalized_headers="$tmpdir/headers.$page.norm"
  tr -d '\r' < "$headers" > "$normalized_headers" || cp -f "$headers" "$normalized_headers"
  last_link=$(grep -i '^link:' "$normalized_headers" 2>/dev/null | tail -n1 || true)
  if [ -n "$last_link" ]; then
    echo "Found Link header: $last_link"
  else
    echo "No Link header found on page $page"
  fi

  if echo "$last_link" | grep -q 'rel="next"'; then
    page=$((page+1))
    continue
  fi

  if [ "$repo_count" -lt "$per_page" ]; then
    echo "Last page reached (page $page). Exiting."
    break
  fi

  page=$((page+1))
done

exit 0
