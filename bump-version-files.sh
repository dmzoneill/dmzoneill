#!/usr/bin/env bash
# Replace an old version with a new one in known version fields only.
# Usage: bump-version-files.sh OLD NEW [APP_NAME]   (run from the repo root)
# The old version is regex-escaped and each replacement is anchored to the
# version field of that file type, so e.g. "192x192" never matches "1.2.4".
set -euo pipefail

old="$1"
new="$2"
app="${3:-}"

esc_old=$(printf '%s' "$old" | sed 's/[][\.*^$/+?(){}|]/\\&/g')
esc_new=$(printf '%s' "$new" | sed 's/[\/&]/\\&/g')
# Version must not be part of a longer number/version string.
pre='(^|[^0-9A-Za-z.])'
post='([^0-9A-Za-z.]|$)'

rep() { # rep FILE LINE_PREFIX_REGEX
  local f="$1" prefix="$2"
  [ -f "$f" ] || return 0
  sed -E -i "s/(${prefix})${esc_old}${post}/\\1${esc_new}\\3/" "$f"
}
rep_any() { # boundary-anchored match anywhere in the line (free-text files)
  local f="$1"
  [ -f "$f" ] || return 0
  sed -E -i "s/${pre}${esc_old}${post}/\\1${esc_new}\\2/g" "$f"
}

# Note: each prefix contains exactly one capture group (\1); post is \3.
rep control '^Version:[[:space:]]*(epoch:)?'
[ -n "$app" ] && rep "${app}.spec" '^Version:[[:space:]]*()'
rep PKG-INFO '^Version:[[:space:]]*()'
rep pyproject.toml '^version[[:space:]]*=[[:space:]]*(["'"'"'])'
rep setup.py 'version[[:space:]]*=[[:space:]]*(["'"'"'])'
if [ -f version ]; then sed -E -i "s/^${esc_old}\$/${esc_new}/" version; fi
rep_any README.md
for f in chrome-plugin/manifest.json metadata.json package.json manifest.json; do
  rep "$f" '"version"[[:space:]]*:[[:space:]]*(")'
done
for f in *.flatpak.yml *.flatpak.yaml *.flatpak.json; do rep_any "$f"; done
for f in snapcraft.yaml snap/snapcraft.yaml; do
  rep "$f" '^version:[[:space:]]*(["'"'"']?)'
done
rep PKGBUILD '^pkgver=()'
for f in *.nuspec; do rep "$f" '<version>()'; done
for f in flake.nix default.nix; do rep "$f" 'version[[:space:]]*=[[:space:]]*(")'; done
