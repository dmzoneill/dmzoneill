# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

This is `dmzoneill` — a GitHub profile repository that acts as a **portfolio hub and DevOps orchestration center**. It auto-generates a dynamic GitHub profile README, distributes CI/CD workflows and secrets across 100+ owned repositories, publishes blog posts to WordPress from release diffs, and auto-responds to GitHub issues with AI.

## Build & Development Commands

```bash
make lint          # Format updater.py with Black
make bump          # Increment patch version in ./version file
make version       # lint + bump + git commit
make push          # lint + bump + commit + pull --rebase + force push to main
make all           # Same as make push (default target)
```

The version is stored in `version` (format: `version=X.Y.Z`). `make bump` increments the last segment.

## Running Scripts Directly

All scripts are Python 3 and depend on the `requests` library. They require environment variables for API tokens (see Secrets section below).

```bash
python updater.py                # Generate README.md from GitHub API + template.md
python setup.py                  # Distribute GitHub Actions secrets to all owned repos
python ai-responder.py           # Respond to a GitHub issue with GPT-4o (needs OPENAI_API_KEY, GITHUB_TOKEN, GITHUB_REPOSITORY, ISSUE_NUMBER)
python wp-pipeline-publisher.py  # Generate and publish WordPress blog post from release diff
python redis-notify.py <message> # Send pipeline status notification to Webdis/Redis
./setup.sh                       # Deploy main.yml and ai-responder.yml workflows to all owned repos
```

## Architecture

### Core Pipeline (this repo's own CI)

`main.yml` workflow: push/schedule trigger → super-linter → run `updater.py` → publish updated README.md to main branch.

### README Generation (`updater.py`)

`ReadmeUpdater` class reads `config.json` (API URLs, badge mappings, live project links, organizations) and `template.md` (HTML template with custom tags like `<repos>`, `<issues>`, `<prs>`, `<recent>`, `<gists>`, `<orgs>`, `<langs>`). It fetches data from GitHub API (repos, issues, PRs, languages, events, gists) and populates the template via regex substitution to produce `README.md`. Rate-limited requests use retry logic with 0.5s delays.

### Reusable Dispatch Workflow (`.github/workflows/dispatch.yaml`)

A ~1400-line reusable workflow (`workflow_call`) consumed by child repositories. It accepts 60+ boolean inputs to toggle validators and publishing targets. Pipeline stages: lint (super-linter) → unit tests → integration tests → version bump → GitHub release → publish to multiple targets (PyPI, npm, Chrome Web Store, GNOME Extensions, Pling, Docker Hub/GHCR, Debian/RPM/Flatpak packages) → WordPress blog post → Redis notifications.

### Workflow Distribution (`setup.sh`)

Iterates all owned repos via GitHub API pagination, compares md5 checksums of existing workflow files against local copies, and pushes `main.yml` + `ai-responder.yml` to repos missing or outdated files. Also sets the `profile_hook` secret on repos where the token has admin permissions.

### Secret Distribution (`setup.py`)

Reads 14 secrets from environment variables and sets them on all owned repositories via `gh secret set`. Secrets include: `PROFILE_HOOK`, `AI_API_KEY`, `AI_MODEL`, `DOCKER_TOKEN`, `PYPI_TOKEN`, `WORDPRESS_*`, `YOUTUBE_API`, `UNSPLASH_ACCESS_KEY`, `CI_USERNAME`, `CI_PASSWORD`, `REDIS_PASSWORD`.

### Blog Publisher (`wp-pipeline-publisher.py`)

Triggered post-release in the dispatch workflow. Fetches the latest commit diff, checks if the change is "substantial" (feat/fix/perf commits, or 25+ changed lines in non-doc files, or `Blog = true` in commit message). If so, generates an HTML blog post via OpenAI, enriches with Unsplash images and YouTube videos, and publishes to WordPress via REST API.

### AI Issue Responder (`ai-responder.py`)

Triggered by `ai-responder.yml` on issue open events. Reads the issue title/body, generates a reply via OpenAI GPT-4o, and posts it as a comment.

## Key Configuration Files

- `config.json` — GitHub API URLs, badge image mappings, live project links, organization list
- `template.md` — HTML template for README generation with custom XML-like tags
- `version` — Current version number (`version=X.Y.Z`)
- `.github/linters/` — ESLint, RuboCop, stylelint, htmlhint, jscpd configs for super-linter

## Git Workflow

Single-branch model (`main`). Daily automated commits from CI with message format: `Automated publish: <date> <previous_sha>`. The Makefile uses `git push -f` (force push).
