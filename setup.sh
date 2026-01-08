#!/bin/bash -x

# Fixes pagination and robustness for updating repositories with workflows.
# Uses the GitHub API Link header to detect next page, caches responses,
# and authenticates once at the start (if PROFILE_HOOK is provided).

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
  jq -r '.[] | .ssh_url' "$body" | while IFS= read -r X; do
    # Extract name from ssh_url which is usually like git@github.com:owner/name.git
    # This works by taking the part after the colon or last slash.
    name=$(basename "$X" | sed 's/\.git$//')
    echo "Checking repo: $name"

    # Set the secret for the repo (no-op if already set)
    if [ -n "$pass" ]; then
      gh secret set profile_hook -r "$user/$name" -b "$pass" || echo "Failed to set secret for $name"
    fi

    # Skip the repository that is this repository itself
    [[ "$name" == "$user" ]] && continue

    # === Check main.yml
    main_url="https://raw.githubusercontent.com/$user/$name/main/.github/workflows/main.yml"
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
    ai_url="https://raw.githubusercontent.com/$user/$name/main/.github/workflows/ai-responder.yml"
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

    echo "$name: main_status=$main_status, main_md5=$main_md5, local_main_md5=$local_main_md5"
    echo "$name: ai_status=$ai_status, ai_md5=$ai_md5, local_ai_md5=$local_ai_md5"

    skip_main="false"
    skip_ai="false"

    # Only copy if file doesn't exist - don't update existing files
    [[ "$main_status" == "present" ]] && skip_main="true"
    [[ "$ai_status" == "present" ]] && skip_ai="true"

    if [[ "$skip_main" == "true" && "$skip_ai" == "true" ]]; then
      echo "Skip: both files already exist in $name"
      continue
    fi

    git_url="https://$user:$pass@github.com/$user/$name.git"
    if ! git clone "$git_url"; then
      echo "Failed to clone $git_url"
      continue
    fi

    [ ! -f "$name/LICENSE" ] && cp LICENSE "$name/" || true

    mkdir -vp "$name/.github/workflows/"
    [[ "$skip_main" != "true" ]] && cp -f main.yml "$name/.github/workflows/" || true
    [[ "$skip_ai" != "true" ]] && cp -f ai-responder.yml "$name/.github/workflows/" || true

    (
      cd "$name" || exit 1
      # Attempt to set secret again in the repo's context
      if [ -n "$pass" ]; then
        gh secret set profile_hook -r "$user/$name" -b "$pass" || echo "Failed to set secret inside $name"
      fi
      git config --global user.email "$email"
      git config --global user.name "$user"

      git remote set-url origin "$git_url"
      git add -A
      # Only commit if there are changes
      if ! git diff --cached --quiet; then
        git commit -m "Add or update GitHub Actions workflows" || echo "git commit had no changes or failed"
        git pull --rebase || echo "git pull --rebase failed in $name"
        git push || echo "git push failed in $name"
      else
        echo "No changes to commit in $name"
      fi
    )
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
