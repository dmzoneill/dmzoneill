#!/usr/bin/env bash
# Proves bump-version-files.sh only changes version fields.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp -r "$root/tests/fixtures/bump/." "$work/"
cd "$work"
"$root/bump-version-files.sh" 1.2.4 1.2.5 app
fail=0
expect() { grep -qxF -- "$2" "$1" || { echo "FAIL $1: missing: $2"; fail=1; }; }
expect app.spec 'Version: 1.2.5'
expect app.spec 'Source1: icons/192x192/app.png'
expect app.spec '%{_datadir}/icons/hicolor/192x192/apps/app.png'
expect pyproject.toml 'version = "1.2.5"'
expect pyproject.toml 'deps = ["foo>=11.2.40"]'
expect package.json '  "version": "1.2.5",'
expect package.json '  "icon": "192x192.png",'
expect package.json '  "dep": "^1.2.45"'
expect version '1.2.5'
expect control 'Version: 1.2.5'
expect control 'Requires: libfoo (>= 1.2.40)'
expect PKGBUILD 'pkgver=1.2.5'
expect PKGBUILD 'source=(192x192.png)'
expect README.md '# App 1.2.5'
expect README.md 'Icon 192x192, needs lib 11.2.4 and 1.2.45.'
[ "$fail" = 0 ] && echo "PASS: only version fields changed"
exit "$fail"
