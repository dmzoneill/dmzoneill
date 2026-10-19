#!/usr/bin/env python3
# pylint: disable=invalid-name
# The hyphenated module name is part of the download URL used by every repo.
"""Reply to new GitHub issues and pull requests with an AI-generated comment."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import requests


def get_issue_content(repo, issue_number, github_token):
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["title"], data["body"] or "", data["html_url"], data["user"]["login"]


def get_pr_content(repo, pr_number, github_token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data["title"], data["body"] or "", data["html_url"], data["user"]["login"]


def get_pr_diff(repo, pr_number, github_token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    diff = response.text
    if len(diff) > 10000:
        diff = diff[:10000] + "\n\n... (diff truncated)"
    return diff


def get_oauth_bearer_token(credentials_path):
    with open(credentials_path, "r", encoding="utf-8") as f:
        cred_data = json.load(f)

    refresh_token = cred_data.get("refresh_token")
    client_id = cred_data.get("client_id")
    client_secret = cred_data.get("client_secret")

    if not all([refresh_token, client_id, client_secret]):
        raise ValueError("Invalid Google credentials file: missing client_id, client_secret, or refresh_token")

    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    resp = requests.post(token_url, data=payload, timeout=15)
    resp.raise_for_status()
    token_json = resp.json()

    access_token = token_json.get("access_token")
    quota_project = cred_data.get("quota_project_id") or os.getenv("GOOGLE_CLOUD_PROJECT")
    return access_token, quota_project


class OpenCodeCliError(RuntimeError):
    """Failure from the official OpenCode CLI, classified for logging."""

    def __init__(self, detail, kind):
        super().__init__(_truncate(_redact(detail, os.getenv("OPENCODE_API_KEY", ""))))
        self.kind = kind


def _opencode_model_id(model):
    text = (model or "big-pickle").strip() or "big-pickle"
    lowered = text.lower()
    for prefix in ("opencode/", "oc/"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return f"opencode/{text}"


def _opencode_models():
    requested_model = os.getenv("OPENCODE_MODEL", "big-pickle")
    return list(
        dict.fromkeys(
            [
                _opencode_model_id(requested_model),
                "opencode/big-pickle",
                "opencode/mimo-v2.6-flash-free",
            ]
        )
    )


def _opencode_binary():
    override = os.getenv("OPENCODE_BIN", "").strip()
    if override:
        return override
    found = shutil.which("opencode")
    if found:
        return found
    default = os.path.expanduser("~/.opencode/bin/opencode")
    if os.path.isfile(default) and os.access(default, os.X_OK):
        return default
    return None


def _reply_config():
    """Text-only agent config. Sharing stays off; tools cannot change the repo."""
    denied = "deny"
    return {
        "$schema": "https://opencode.ai/config.json",
        "share": "disabled",
        "agent": {
            "reply": {
                "description": "Write a GitHub comment without changing files",
                "mode": "primary",
                "temperature": 0.4,
                "steps": 4,
                "permission": {
                    "edit": denied,
                    "bash": denied,
                    "task": denied,
                    "question": denied,
                    "webfetch": denied,
                    "websearch": denied,
                    "lsp": denied,
                    "skill": denied,
                    "external_directory": denied,
                },
            }
        },
    }


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _truncate(text, limit=4000):
    if len(text) <= limit:
        return text
    lowered = text.lower()
    for marker in ("freetiererror", "free tier can only be used", "can only be used from within opencode"):
        index = lowered.find(marker)
        if index == -1:
            continue
        start = max(0, index - 500)
        end = min(len(text), index + 1500)
        snippet = text[start:end]
        return f"{text[:800]}\n... (log truncated) ...\n{snippet}\n... (log truncated) ...\n{text[-800:]}"
    head = limit // 2
    return f"{text[:head]}\n... (log truncated) ...\n{text[-head:]}"


def _redact(text, secret):
    if secret and secret in text:
        return text.replace(secret, "[REDACTED]")
    return text


def _record(line):
    print(line, file=sys.stderr)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _refusal_kind(detail):
    lowered = detail.lower()
    free_tier_markers = (
        "freetiererror",
        "free tier can only be used",
        "can only be used from within opencode",
    )
    if any(marker in lowered for marker in free_tier_markers):
        return "free_tier"
    auth_markers = (
        "unauthorized",
        "invalid api key",
        "invalid_api_key",
        "authentication failed",
        "forbidden",
    )
    if any(marker in lowered for marker in auth_markers) or " 401" in f" {lowered}" or "(401)" in lowered:
        return "auth"
    if " 403" in f" {lowered}" or "(403)" in lowered or '"status":403' in lowered or "status code 403" in lowered:
        return "auth"
    model_markers = ("model not found", "unknown model", "no such model", "model_not_found")
    if any(marker in lowered for marker in model_markers) or "404" in lowered or "410" in lowered:
        return "model"
    return "other"


def _log_opencode(model, kind, detail, auth_mode):
    safe = _truncate(_redact(detail, os.getenv("OPENCODE_API_KEY", "")))
    label = {
        "free_tier": "provider refusal",
        "auth": "auth refusal",
        "model": "model unavailable",
    }.get(kind, "error")
    _record(f"OPENCODE_CLI_RESULT status=refused model={model} kind={kind} auth={auth_mode}")
    _record(f"OpenCode CLI {label} for {model} ({auth_mode}): {safe}")


def _cli_timeout():
    raw = os.getenv("OPENCODE_RUN_TIMEOUT", "180")
    try:
        return max(30, int(raw))
    except ValueError:
        return 180


def _cli_env(api_key):
    env = os.environ.copy()
    if api_key:
        env["OPENCODE_API_KEY"] = api_key
    else:
        env.pop("OPENCODE_API_KEY", None)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "true"
    env["OPENCODE_DISABLE_LSP_DOWNLOAD"] = "true"
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(_reply_config())
    # The official CLI sets its own client id. Do not override it.
    env.pop("OPENCODE_CLIENT", None)
    return env


def _event_text(event):
    if event.get("type") != "text":
        return ""
    part = event.get("part")
    if isinstance(part, dict) and part.get("text"):
        return str(part["text"])
    return ""


def _event_error(event):
    if event.get("type") != "error":
        return ""
    payload = event.get("error", event)
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False)


def _parse_cli_events(stdout):
    texts = []
    errors = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        text = _event_text(event)
        if text:
            texts.append(text)
        error = _event_error(event)
        if error:
            errors.append(error)
    return "\n".join(texts).strip(), "\n".join(errors).strip()


def _prepare_workdir(workdir):
    try:
        subprocess.run(["git", "init", "-q", workdir], check=False, capture_output=True)
    except OSError:
        pass


def _cli_command(binary, model, workdir, prompt_text):
    message = prompt_text + "\n\nReply with the GitHub comment text only. Do not edit files or run commands."
    return [
        binary,
        "run",
        "--format",
        "json",
        "--model",
        model,
        "--agent",
        "reply",
        "--dir",
        workdir,
        message,
    ]


def _run_opencode_cli(binary, model, prompt_text, api_key):
    timeout = _cli_timeout()
    with tempfile.TemporaryDirectory(prefix="opencode-reply-") as workdir:
        _prepare_workdir(workdir)
        try:
            completed = subprocess.run(
                _cli_command(binary, model, workdir, prompt_text),
                cwd=workdir,
                env=_cli_env(api_key),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            detail = f"opencode run timed out after {exc.timeout}s\n{_as_text(exc.stderr)}\n{_as_text(exc.stdout)}"
            raise OpenCodeCliError(detail.strip(), "other") from exc

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    reply, errors = _parse_cli_events(stdout)
    if reply:
        return reply
    detail_parts = [stderr.strip(), errors]
    if not errors:
        detail_parts.append(stdout.strip())
    detail = "\n".join(part for part in detail_parts if part)
    if not detail:
        detail = f"opencode run exited {completed.returncode} with no output"
    raise OpenCodeCliError(detail.strip(), _refusal_kind(detail))


def _opencode_attempts(api_key):
    """Try the Zen key first. Free models also work with the CLI's own login-less path."""
    attempts = []
    if api_key:
        attempts.append(("with_api_key", api_key, _opencode_models()))
    attempts.append(("without_api_key", "", ["opencode/big-pickle", "opencode/mimo-v2.6-flash-free"]))
    return attempts


def _opencode_attempt(binary, prompt_text, auth_mode, api_key, models):
    last_error = None
    for model in models:
        try:
            reply = _run_opencode_cli(binary, model, prompt_text, api_key)
        except OpenCodeCliError as exc:
            last_error = str(exc)
            _log_opencode(model, exc.kind, last_error, auth_mode)
            if exc.kind in {"free_tier", "auth"}:
                return None, last_error, exc.kind
            continue
        except OSError as exc:
            last_error = str(exc)
            _log_opencode(model, "other", last_error, auth_mode)
            continue
        _record(f"OPENCODE_CLI_RESULT status=ok model={model} auth={auth_mode}")
        _record("AI_RESPONDER_PROVIDER=opencode")
        return reply, None, None
    return None, last_error, "other"


def generate_opencode_reply(prompt_text, api_key):
    binary = _opencode_binary()
    if not binary:
        message = "OpenCode CLI is not installed. Install it with: curl -fsSL https://opencode.ai/install | bash"
        _log_opencode("none", "other", message, "with_api_key" if api_key else "without_api_key")
        raise RuntimeError(message)

    last_error = None
    for auth_mode, attempt_key, models in _opencode_attempts(api_key):
        reply, last_error, _ = _opencode_attempt(binary, prompt_text, auth_mode, attempt_key, models)
        if reply:
            return reply

    raise RuntimeError(f"OpenCode CLI generation failed: {last_error}")


def _gemini_auth():
    """Return the request headers and query string for Gemini authentication."""
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    api_key = os.getenv("GEMINI_API_KEY")
    headers = {"Content-Type": "application/json"}

    if cred_path and os.path.exists(cred_path):
        access_token, quota_project = get_oauth_bearer_token(cred_path)
        headers["Authorization"] = f"Bearer {access_token}"
        if quota_project:
            headers["x-goog-user-project"] = quota_project
        return headers, ""
    if api_key:
        return headers, f"?key={api_key}"
    raise RuntimeError("Missing Gemini authentication: set GOOGLE_APPLICATION_CREDENTIALS or GEMINI_API_KEY.")


def _gemini_content(data):
    candidates = data.get("candidates", [])
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts", [])
    if parts and "text" in parts[0]:
        return parts[0]["text"].strip()
    return None


def generate_gemini_reply(prompt_text):
    headers, query_params = _gemini_auth()

    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "gemini-flash-latest",
        "gemini-3.6-flash",
    ]
    models_to_try = list(dict.fromkeys(candidate_models))

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 2048,
        },
    }

    last_error = None
    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent{query_params}"
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                content = _gemini_content(response.json())
                if content:
                    return content
            elif response.status_code == 404:
                last_error = f"Model {model} returned 404: {response.text}"
                continue
            else:
                last_error = f"Gemini API error ({response.status_code}): {response.text}"
        except (requests.RequestException, ValueError) as e:
            last_error = str(e)

    raise RuntimeError(f"Gemini generation failed: {last_error}")


def generate_ai_reply(prompt_text):
    opencode_key = os.getenv("OPENCODE_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if opencode_key or _opencode_binary():
        try:
            return generate_opencode_reply(prompt_text, opencode_key or "")
        except RuntimeError as exc:
            if not (gemini_key or (cred_path and os.path.exists(cred_path))):
                raise
            print(f"OpenCode CLI generation failed: {exc}", file=sys.stderr)
            print("OpenCode CLI did not produce a reply; trying Gemini fallback.", file=sys.stderr)

    if (cred_path and os.path.exists(cred_path)) or gemini_key:
        reply = generate_gemini_reply(prompt_text)
        _record("AI_RESPONDER_PROVIDER=gemini")
        return reply

    raise RuntimeError(
        "Missing authentication: set OPENCODE_API_KEY, GEMINI_API_KEY, or GOOGLE_APPLICATION_CREDENTIALS."
    )


def post_comment(repo, number, comment, github_token, is_pr=False):
    if is_pr:
        url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
    else:
        url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.post(url, headers=headers, json={"body": comment}, timeout=10)
    response.raise_for_status()


def send_telegram(bot_token, chat_id, message):
    if not bot_token or not chat_id:
        print("Telegram secrets not set, skipping notification")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        print("Telegram notification sent")
    except requests.RequestException as e:
        print(f"Failed to send Telegram notification: {e}")


def handle_issue():
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    issue_number = os.getenv("ISSUE_NUMBER")

    if not all([github_token, repo, issue_number]):
        raise RuntimeError("Missing required environment variables.")

    title, body, issue_url, author = get_issue_content(repo, issue_number, github_token)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ISSUES_CHAT_ID")
    message = f"New issue on {repo}\n\nTitle: {title}\nBy: {author}\n\n{body}\n\n{issue_url}"
    send_telegram(bot_token, chat_id, message)

    repo_url = os.getenv("ISSUE_REPO_URL", "")
    prompt = "You're a helpful AI assistant. Reply concisely to the following GitHub issue.\n"
    if repo_url:
        prompt += f"The source code is available at: {repo_url}\n"
    prompt += f"\n\n{title}\n\n{body}"

    comment = generate_ai_reply(prompt)
    post_comment(repo, issue_number, comment, github_token)


def handle_pr():
    github_token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    pr_number = os.getenv("PR_NUMBER")

    if not all([github_token, repo, pr_number]):
        raise RuntimeError("Missing required environment variables.")

    title, body, pr_url, author = get_pr_content(repo, pr_number, github_token)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_PR_CHAT_ID")
    message = f"New PR on {repo}\n\nTitle: {title}\nBy: {author}\n\n{body}\n\n{pr_url}"
    send_telegram(bot_token, chat_id, message)

    diff = get_pr_diff(repo, pr_number, github_token)
    repo_url = os.getenv("ISSUE_REPO_URL", "")
    prompt = "You're a helpful AI code reviewer. Review the following pull request concisely.\n"
    prompt += "Summarize the changes and flag any potential issues.\n"
    if repo_url:
        prompt += f"The source code is available at: {repo_url}\n"
    prompt += f"\nTitle: {title}\n\nDescription: {body}\n\nDiff:\n{diff}"

    comment = generate_ai_reply(prompt)
    post_comment(repo, pr_number, comment, github_token, is_pr=True)


def handle_dry_run():
    prompt = os.getenv("AI_RESPONDER_PROMPT", "Reply with exactly the single word: pong")
    print("AI responder dry run: generating a reply without posting a comment", file=sys.stderr)
    comment = generate_ai_reply(prompt)
    print("AI_RESPONDER_OUTPUT_BEGIN")
    print(comment)
    print("AI_RESPONDER_OUTPUT_END")


def main():
    event_type = os.getenv("EVENT_TYPE", "issue")

    if event_type == "pull_request":
        handle_pr()
    elif event_type == "dry_run":
        handle_dry_run()
    else:
        handle_issue()


if __name__ == "__main__":
    main()
