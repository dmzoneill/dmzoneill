#!/bin/bash -x

# Robust updater for adding workflows and Dependabot config to repositories owned by $user.
# - Uses GitHub API pagination and Link header detection
# - Authenticates once if PROFILE_HOOK provided
# - Filters to only repos owned by $user (even when using /user/repos)
# - Clones into temporary per-repo directories to avoid name collisions
# - Sets secret only when possible; skips repos without admin rights
# - Writes .github/dependabot.yml from dependabot.yml for ecosystems detected in the repo
# - Points main.yml push/pull_request filters at the repository default branch

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

# Codacy / CodeQL / SonarCloud caller stubs (logic lives in reusable
# workflows under .github/workflows/ here). Off unless the hub repo variable
# DISTRIBUTE_SECURITY_WORKFLOWS is "true". DRY_RUN=true only reports.
security_workflows="codacy.yml codeql.yml sonarcloud.yml"
security_marker="Managed by https://github.com/dmzoneill/dmzoneill setup.sh"
distribute_security=${DISTRIBUTE_SECURITY_WORKFLOWS:-false}
dry_run=${DRY_RUN:-false}

# Print the security stubs repo_full should receive, one per line.
# Missing -> add; our stub but outdated -> update; anything else -> leave.
plan_security_workflows() {
  local repo_full="$1"
  local raw_root="$2"
  local archived="$3"
  local fork="$4"
  local private="$5"
  local wf remote_md5 local_md5

  if [[ "$archived" == "true" || "$fork" == "true" ]]; then
    echo "$repo_full: security workflows skipped (archived=$archived fork=$fork)" >&2
    return
  fi
  for wf in $security_workflows; do
    [ -f "$wf" ] || continue
    if [[ "$wf" == "codeql.yml" ]]; then
      if [[ "$private" == "true" ]]; then
        echo "$repo_full: codeql.yml skipped (private repo)" >&2
        continue
      fi
      if [[ "$(gh api "repos/$repo_full/code-scanning/default-setup" --jq .state 2>/dev/null)" == "configured" ]]; then
        echo "$repo_full: codeql.yml skipped (CodeQL default setup enabled)" >&2
        continue
      fi
    fi
    local_md5=$(md5sum "$wf" | awk '{print $1}')
    if ! curl -s -f -L "$raw_root/.github/workflows/$wf" >/tmp/sec_check 2>/dev/null; then
      echo "$repo_full: $wf missing, will add" >&2
      echo "$wf"
      continue
    fi
    remote_md5=$(md5sum /tmp/sec_check | awk '{print $1}')
    if [[ "$remote_md5" == "$local_md5" ]]; then
      continue
    fi
    if grep -qF "$security_marker" /tmp/sec_check; then
      echo "$repo_full: $wf outdated stub, will update" >&2
      echo "$wf"
    else
      echo "$repo_full: $wf customized, leaving untouched" >&2
    fi
  done
}

# Authenticate once (so gh and API requests can use the token)
if [ -n "$pass" ]; then
  echo "$pass" >.githubtoken
  unset GITHUB_TOKEN
  if ! gh auth login --with-token <.githubtoken; then
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
  git@github.com:*/*)
    current_full=${origin_url#git@github.com:}
    current_full=${current_full%.git}
    ;;
  https://github.com/*/*)
    current_full=${origin_url#https://github.com/}
    current_full=${current_full%.git}
    ;;
  *) current_full="" ;;
  esac
fi

process_repo() {
  local repo_owner="$1"
  local repo_name="$2"
  local repo_clone_url="$3"
  local can_set_secrets="$4"
  local default_branch="$5"
  local repo_archived="${6:-false}"
  local repo_fork="${7:-false}"
  local repo_private="${8:-false}"
  local repo_full="$repo_owner/$repo_name"

  if [ -z "$default_branch" ] || [ "$default_branch" = "null" ]; then
    default_branch="main"
  fi

  if [ -n "$current_full" ] && [ "$repo_full" = "$current_full" ]; then
    echo "Skipping current repository $repo_full"
    return
  fi

  local raw_root="https://raw.githubusercontent.com/$repo_owner/$repo_name/$default_branch"
  local main_url="$raw_root/.github/workflows/main.yml"
  local main_status="missing"
  local main_md5=""
  if curl -s -f -L "$main_url" >/tmp/main_check 2>/dev/null; then
    if grep -q "^name:" /tmp/main_check; then
      main_status="present"
      main_md5=$(md5sum /tmp/main_check 2>/dev/null | awk '{print $1}')
    else
      main_status="corrupt"
    fi
  fi

  # The AI responder workflow is retired: remove it where it still exists.
  local ai_url="$raw_root/.github/workflows/ai-responder.yml"
  local remove_ai="false"
  if [[ "$repo_archived" != "true" && "$repo_fork" != "true" ]] &&
    curl -s -f -L -o /dev/null "$ai_url" 2>/dev/null; then
    remove_ai="true"
  fi

  echo "$repo_full: main_status=$main_status, main_md5=$main_md5, local_main_md5=$local_main_md5"
  echo "$repo_full: remove_ai=$remove_ai"

  local skip_main="false"
  local patch_main="false"
  local skip_dep="false"
  if [[ "$main_status" == "present" ]]; then
    local branch_rc
    python3 distribute.py needs-default-branch /tmp/main_check "$default_branch"
    branch_rc=$?
    if [[ "$branch_rc" -eq 0 ]]; then
      skip_main="true"
    elif [[ "$branch_rc" -eq 1 ]]; then
      patch_main="true"
    else
      echo "Could not check default-branch trigger in $repo_full; leaving main.yml"
      skip_main="true"
    fi
  fi

  rm -f /tmp/dep_check /tmp/dep_expected
  local dep_url="$raw_root/.github/dependabot.yml"
  if curl -s -f -L "$dep_url" >/tmp/dep_check 2>/dev/null; then
    echo "$repo_full: dependabot present"
  else
    echo "$repo_full: dependabot missing"
    rm -f /tmp/dep_check
  fi
  if python3 distribute.py dependabot-remote "$repo_owner" "$repo_name" "$default_branch" \
    --ensure .github/workflows/main.yml \
    >/tmp/dep_expected; then
    if [[ ! -s /tmp/dep_expected ]]; then
      skip_dep="true"
    elif [[ -f /tmp/dep_check ]] && cmp -s /tmp/dep_expected /tmp/dep_check; then
      skip_dep="true"
    fi
  else
    echo "Dependabot detection failed for $repo_full; leaving dependabot.yml"
    skip_dep="true"
  fi

  local security_todo=""
  if [[ "$distribute_security" == "true" || "$dry_run" == "true" ]]; then
    security_todo=$(plan_security_workflows "$repo_full" "$raw_root" "$repo_archived" "$repo_fork" "$repo_private")
  fi
  if [[ "$dry_run" == "true" ]]; then
    echo "DRY_RUN $repo_full: security=[$(echo "$security_todo" | xargs)] remove_ai=$remove_ai"
    return
  fi

  if [[ "$skip_main" == "true" && "$remove_ai" != "true" && "$skip_dep" == "true" && "$patch_main" != "true" && -z "$security_todo" ]]; then
    echo "Skip: workflows and dependabot already match in $repo_full"
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
  if [[ "$patch_main" == "true" && -f "$target_dir/.github/workflows/main.yml" ]]; then
    python3 distribute.py ensure-default-branch \
      "$target_dir/.github/workflows/main.yml" \
      "$default_branch"
  elif [[ "$skip_main" != "true" ]]; then
    cp -f main.yml "$target_dir/.github/workflows/"
  fi
  if [[ "$remove_ai" == "true" ]]; then
    rm -f "$target_dir/.github/workflows/ai-responder.yml"
  fi
  local wf
  for wf in $security_todo; do
    cp -f "$wf" "$target_dir/.github/workflows/"
  done
  if [[ "$skip_dep" != "true" ]]; then
    if python3 distribute.py dependabot "$target_dir" >/tmp/dep_rendered; then
      if [[ -s /tmp/dep_rendered ]]; then
        cp -f /tmp/dep_rendered "$target_dir/.github/dependabot.yml"
      fi
    else
      echo "Failed to render dependabot.yml for $repo_full"
    fi
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
      git commit -m "Add or update GitHub Actions workflows and Dependabot config" || echo "git commit had no changes or failed"
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

  jq -r --arg OWNER "$user" '.[] | select(.owner.login == $OWNER) | [.owner.login, .name, .ssh_url, .clone_url, .permissions.admin, .default_branch, .archived, .fork, .private] | @tsv' "$body" |
    while IFS=$'\t' read -r repo_owner repo_name repo_ssh repo_clone_url repo_admin default_branch repo_archived repo_fork repo_private; do
      echo "Checking repo: $repo_owner/$repo_name (ssh_url: $repo_ssh, clone_url: $repo_clone_url, admin:$repo_admin)"

      can_set_secrets="false"
      if [ "$repo_admin" = "true" ]; then
        can_set_secrets="true"
      else
        echo "Note: token does not report admin for $repo_owner/$repo_name; skipping secret set"
      fi

      process_repo "$repo_owner" "$repo_name" "$repo_clone_url" "$can_set_secrets" "$default_branch" \
        "$repo_archived" "$repo_fork" "$repo_private"
    done

  # Normalize Link header and pick last Link: line (handles redirects)
  echo "Response headers (raw):"
  sed -n '1,200p' "$headers" || true
  normalized_headers="$tmpdir/headers.$page.norm"
  tr -d '\r' <"$headers" >"$normalized_headers" || cp -f "$headers" "$normalized_headers"
  last_link=$(grep -i '^link:' "$normalized_headers" 2>/dev/null | tail -n1 || true)
  if [ -n "$last_link" ]; then
    echo "Found Link header: $last_link"
  else
    echo "No Link header found on page $page"
  fi

  if echo "$last_link" | grep -q 'rel="next"'; then
    page=$((page + 1))
    continue
  fi

  if [ "$repo_count" -lt "$per_page" ]; then
    echo "Last page reached (page $page). Exiting."
    break
  fi

  page=$((page + 1))
done

# Trigger CI on all owned repos via repository_dispatch
if [ -n "$GITHUB_TOKEN" ] && [ "$dry_run" != "true" ]; then
  echo "Dispatching refresh event to all owned repos..."
  page=1
  while true; do
    body_file="$tmpdir/dispatch_body.$page"
    curl -sS -H "Authorization: token $GITHUB_TOKEN" \
      -o "$body_file" \
      "https://api.github.com/user/repos?per_page=$per_page&page=$page"

    repos=$(jq -r --arg OWNER "$user" '.[] | select(.owner.login == $OWNER) | .full_name' "$body_file" 2>/dev/null)
    [ -z "$repos" ] && break

    for repo_full in $repos; do
      if [ -n "$current_full" ] && [ "$repo_full" = "$current_full" ]; then
        continue
      fi
      echo "Dispatching refresh to $repo_full"
      gh api "repos/$repo_full/dispatches" -f event_type=refresh 2>/dev/null || echo "Failed to dispatch to $repo_full"
    done

    count=$(jq 'length' "$body_file" 2>/dev/null || echo 0)
    [ "$count" -lt "$per_page" ] && break
    page=$((page + 1))
  done
fi

exit 0
