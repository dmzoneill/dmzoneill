#!/bin/bash -x

# Fixes pagination and robustness for updating repositories with workflows.
# Uses the GitHub API Link header to detect next page, caches responses,
# authenticates once at the start (if PROFILE_HOOK is provided),
# and correctly handles repositories owned by orgs or other users.
#
# Key fixes vs previous:
# - Use repo owner and name from API (don't assume owner == $user)
# - Clone into a temporary directory to avoid name collisions (eg ".github")
# - Use per-repo local git config instead of --global
# - Better header normalization and Link: rel="next" detection

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

# Where to place clones (avoid name collisions with repo dirs like ".github")
clone_base="$tmpdir/clones"
mkdir -p "$clone_base"

# Determine current repo full name to skip (if running inside a git repo)
current_full=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  origin_url=$(git config --get remote.origin.url || echo "")
  # Try parse owner/name from origin url
  case "$origin_url" in
    git@github.com:*/*) current_full=${origin_url#git@github.com:}; current_full=${current_full%.git} ;;
    https://github.com/*/*) current_full=${origin_url#https://github.com/}; current_full=${current_full%.git} ;;
    *) current_full="" ;;
  esac
fi

page=1
while true; do
  echo "Page: $page"

  # Use authenticated endpoint when token present to include private repos
  if [ -n "$GITHUB_TOKEN" ]; then
    api_base="https://api.github.com/user/repos"
  else
    api_base="https://api.github.com/users/$user/repos"
  fi
  url="$api_base?per_page=$per_page&page=$page"
  echo "$url"

  headers="$tmpdir/headers.$page"
  body="$tmpdir/body.$page"

  # Use Authorization header for curl if we have a token (helps avoid rate limits)
  if [ -n "$GITHUB_TOKEN" ]; then
    curl -sS -H "Authorization: token $GITHUB_TOKEN" -D "$headers" -o "$body" "$url"
  else
    curl -sS -D "$headers" -o "$body" "$url"
  fi

  # Get the last HTTP status line in case of redirects (multiple header blocks)
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

  # Count repos returned
  repo_count=$(jq 'length' "$body" 2>/dev/null || echo 0)
  echo "Repos on this page (jq length): $repo_count"

  # If no repos, we're done
  if [ "$repo_count" -eq 0 ]; then
    echo "No repos on page $page, exiting"
    break
  fi

  # Iterate repos from cached body (preserves safety for names with spaces)
  # Use owner and name explicitly so we don't assume owner == $user
  jq -r '.[] | [.owner.login, .name, .ssh_url] | @tsv' "$body" | \
  while IFS=$'\t' read -r repo_owner repo_name repo_ssh; do
    repo_full="$repo_owner/$repo_name"
    echo "Checking repo: $repo_full (ssh_url: $repo_ssh)"

    # Skip the repository that is this repository itself
    if [ -n "$current_full" ] && [ "$repo_full" = "$current_full" ]; then
      echo "Skipping current repository $repo_full"
      continue
    fi

    # Set the secret for the repo (no-op if already set). Use the repo full name.
    if [ -n "$pass" ]; then
      gh secret set profile_hook -r "$repo_full" -b "$pass" || echo "Failed to set secret for $repo_full"
    fi

    # === Check main.yml
    main_url="https://raw.githubusercontent.com/$repo_owner/$repo_name/main/.github/workflows/main.yml"
    if curl -s -f -L "$main_url" > /tmp/main_check 2>/dev/null; then
      if grep -q "^name:" /tmp/main_check; then
        main_status="present"
        main_md5=$(md5sum /tmp/main_check 2>/dev/null | awk '{print $1}')
      else
        main_status="corrupt"
        main_md5=""
      fi
    else
      main_status="missing"
      main_md5=""
    fi

    # === Check ai-responder.yml
    ai_url="https://raw.githubusercontent.com/$repo_owner/$repo_name/main/.github/workflows/ai-responder.yml"
    if curl -s -f -L "$ai_url" > /tmp/ai_check 2>/dev/null; then
      if grep -q "^name:" /tmp/ai_check; then
        ai_status="present"
        ai_md5=$(md5sum /tmp/ai_check 2>/dev/null | awk '{print $1}')
      else
        ai_status="corrupt"
        ai_md5=""
      fi
    else
      ai_status="missing"
      ai_md5=""
    fi

    echo "$repo_full: main_status=$main_status, main_md5=$main_md5, local_main_md5=$local_main_md5"
    echo "$repo_full: ai_status=$ai_status, ai_md5=$ai_md5, local_ai_md5=$local_ai_md5"

    skip_main="false"
    skip_ai="false"

    # Only copy if file doesn't exist - don't update existing files
    [[ "$main_status" == "present" ]] && skip_main="true"
    [[ "$ai_status" == "present" ]] && skip_ai="true"

    if [[ "$skip_main" == "true" && "$skip_ai" == "true" ]]; then
      echo "Skip: both files already exist in $repo_full"
      continue
    fi

    # Build clone URL. If we have credentials use them to avoid rate limits for large batches.
    if [ -n "$pass" ]; then
      git_url="https://$user:$pass@github.com/$repo_owner/$repo_name.git"
    else
      git_url="https://github.com/$repo_owner/$repo_name.git"
    fi

    target_dir="$clone_base/$repo_owner-$repo_name"
    rm -rf "$target_dir"
    if ! git clone --depth 1 "$git_url" "$target_dir"; then
      echo "Failed to clone $git_url (into $target_dir)"
      continue
    fi

    # Copy LICENSE from this repo if target doesn't have it and current repo has it
    if [ -f LICENSE ] && [ ! -f "$target_dir/LICENSE" ]; then
      cp -f LICENSE "$target_dir/" || true
    fi

    mkdir -p "$target_dir/.github/workflows/"
    [[ "$skip_main" != "true" ]] && cp -f main.yml "$target_dir/.github/workflows/" || true
    [[ "$skip_ai" != "true" ]] && cp -f ai-responder.yml "$target_dir/.github/workflows/" || true

    (
      cd "$target_dir" || exit 1
      # Attempt to set secret again in the repo's context
      if [ -n "$pass" ]; then
        gh secret set profile_hook -r "$repo_full" -b "$pass" || echo "Failed to set secret inside $repo_full"
      fi

      # Use local repo config rather than global
      git config user.email "$email"
      git config user.name "$user"

      git remote set-url origin "$git_url"
      git add -A
      # Only commit if there are changes
      if ! git diff --cached --quiet; then
        git commit -m "Add or update GitHub Actions workflows" || echo "git commit had no changes or failed"
        git pull --rebase || echo "git pull --rebase failed in $repo_full"
        git push || echo "git push failed in $repo_full"
      else
        echo "No changes to commit in $repo_full"
      fi
    )

    # Clean up clone to save space; comment out if you want to keep clones.
    rm -rf "$target_dir"
  done

  # Debug: show raw headers (trimmed)
  echo "Response headers (raw):"
  sed -n '1,200p' "$headers" || true

  # Normalize CRLFs (remove CR) and take the last Link header (handles redirects/multiple header blocks)
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

  # If Link header didn't indicate next, but fewer than per_page repos were returned,
  # assume this is the last page.
  if [ "$repo_count" -lt "$per_page" ]; then
    echo "Last page reached (page $page). Exiting."
    break
  fi

  # Otherwise increment page and continue
  page=$((page+1))
done

exit 0
