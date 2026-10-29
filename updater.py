import base64
import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from operator import itemgetter

import requests

RE_FLAGS = re.IGNORECASE | re.MULTILINE | re.DOTALL
REQUEST_TIMEOUT = 30

CACHE_FILE = "generated/cache.json"
CACHE_TTL_HOURS = 12
PERMANENT_CACHE_FILE = "generated/permanent_cache.json"

FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji'"
)


def _timeline_marker(x, line_y, r, year, count):
    return (
        f'  <circle cx="{x:.1f}" cy="{line_y}" r="{r:.1f}" fill="#58a6ff" opacity="0.3"/>\n'
        f'  <circle cx="{x:.1f}" cy="{line_y}" r="{r * 0.6:.1f}" fill="#58a6ff" opacity="0.6"/>\n'
        f'  <circle cx="{x:.1f}" cy="{line_y}" r="{max(3, r * 0.3):.1f}" fill="#58a6ff"/>\n'
        f'  <text x="{x:.1f}" y="{line_y + r + 14:.1f}" class="tyear" text-anchor="middle">{year}</text>\n'
        f'  <text x="{x:.1f}" y="{line_y - r - 6:.1f}" class="tcount" text-anchor="middle">{count}</text>\n'
    )


def _count_years(repos):
    year_counts = defaultdict(int)
    for r in repos:
        y = r.get("first_commit_year") or r.get("get_first_commit_date") or r.get("created_at", "")[:4]
        if y and str(y).isdigit():
            year_counts[int(y)] += 1
    return year_counts


def svg_timeline(repos, width=860, height=150):
    year_counts = _count_years(repos)

    if not year_counts:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"/>'

    min_year = min(year_counts)
    max_year = max(*year_counts, datetime.now(timezone.utc).year)
    if min_year == max_year:
        max_year = min_year + 1
    max_count = max(year_counts.values())

    left = 40
    right = width - 40
    line_y = height // 2 + 15
    span = right - left

    elements = f'  <line x1="{left}" y1="{line_y}" x2="{right}" y2="{line_y}" stroke="#30363d" stroke-width="2"/>\n'

    for year, count in sorted(year_counts.items()):
        elements += _timeline_marker(
            left + (year - min_year) / (max_year - min_year) * span,
            line_y,
            4 + (count / max_count) * 14,
            year,
            count,
        )

    total = sum(year_counts.values())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .card   {{ fill: #161b22; stroke: #30363d; stroke-width: 1; }}
    .head   {{ font: 600 14px {FONT}; fill: #e6edf3; }}
    .tyear  {{ font: 10px {FONT}; fill: #7d8590; }}
    .tcount {{ font: 10px {FONT}; fill: #e6edf3; }}
  </style>
  <rect class="card" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8"/>
  <text class="head" x="16" y="26">Over the years · {total} repos</text>
{elements}
</svg>"""


LANG_COLOURS = {
    "PHP": "#4F5D95",
    "C#": "#178600",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "HTML": "#e34c26",
    "CSS": "#663399",
    "C": "#555555",
    "Perl": "#0298c3",
    "Java": "#b07219",
    "Smarty": "#f0c040",
    "Shell": "#89e051",
    "Go": "#00ADD8",
    "C++": "#f34b7d",
    "Ruby": "#701516",
    "Puppet": "#302B6D",
    "Makefile": "#427819",
}
TOP_LANGUAGES = 20
LIST_LIMIT = 10
SEARCH_ATTEMPTS = 4
FEATURED_COUNT = 6
PROFILE_LOGO = "https://raw.githubusercontent.com/dmzoneill/dmzoneill/main/.github/logo.png"
RECENT_ICONS = {
    "PushEvent": "⬆️",
    "PullRequestEvent": "🔀",
    "IssuesEvent": "🟢",
    "IssueCommentEvent": "💬",
    "CreateEvent": "✨",
    "ReleaseEvent": "🏷️",
    "WatchEvent": "⭐",
    "ForkEvent": "🍴",
}


def lang_colour(lang):
    return LANG_COLOURS.get(lang, "#8b949e")


def human_bytes(size):
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000:.0f} KB"


def svg_languages_bar(languages, width=860, height=14):
    total = sum(size for _, size in languages) or 1
    x = 0.0
    rects = ""
    for lang, size in languages:
        w = size / total * width
        rects += f'  <rect x="{x:.2f}" y="0" width="{w:.2f}" height="{height}" fill="{lang_colour(lang)}"/>\n'
        x += w
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <clipPath id="r"><rect width="{width}" height="{height}" rx="7"/></clipPath>
  <g clip-path="url(#r)">
{rects}  </g>
</svg>"""


ORG_BUTTON_WIDTH = 134
ORG_BUTTON_HEIGHT = 46


def svg_org_button(label, count, avatar_uri, width=ORG_BUTTON_WIDTH, height=ORG_BUTTON_HEIGHT):
    """A fixed-size dark button with the org avatar, label and count."""
    label = html_escape(label)
    text_width = width - 50
    avatar = (
        f'<image href="{avatar_uri}" x="9" y="{(height - 28) / 2:.0f}" width="28" height="28" clip-path="url(#a)"/>'
        if avatar_uri
        else f'<circle cx="23" cy="{height / 2:.0f}" r="14" fill="#30363d"/>'
    )
    fit = f' textLength="{text_width}" lengthAdjust="spacingAndGlyphs"' if len(label) > 13 else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <clipPath id="a"><rect x="9" y="{(height - 28) / 2:.0f}" width="28" height="28" rx="6"/></clipPath>
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" fill="#161b22" stroke="#30363d"/>
  {avatar}
  <text x="44" y="20" font-family="{FONT}" font-size="12" font-weight="600" fill="#4493f8"{fit}>{label}</text>
  <text x="44" y="35" font-family="{FONT}" font-size="11" fill="#9198a1">{count}</text>
</svg>"""


TILE_WIDTH = 176
TILE_HEIGHT = 46
TILES = {
    "gist": ("📝", "Gists"),
    "issue": ("🟢", "Issues"),
    "pr": ("🔀", "Pull requests"),
    "activity": ("⚡", "Activity"),
}


def svg_tile(icon, title, subtitle, width=TILE_WIDTH, height=TILE_HEIGHT):
    """A fixed-size dark card matching the org buttons, with an emoji icon, title and subtitle."""
    subtitle = html_escape(subtitle)
    top = (height - 28) / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="8" fill="#161b22" stroke="#30363d"/>
  <rect x="9" y="{top:.0f}" width="28" height="28" rx="6" fill="#21262d"/>
  <text x="23" y="{top + 19:.0f}" font-size="15" text-anchor="middle">{icon}</text>
  <text x="44" y="20" font-family="{FONT}" font-size="12" font-weight="600" fill="#4493f8">{html_escape(title)}</text>
  <text x="44" y="35" font-family="{FONT}" font-size="11" fill="#9198a1">{subtitle}</text>
</svg>"""


def shorten(text, limit):
    text = (text or "").strip().replace("|", "-")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def relative_time(timestamp):
    """Render an ISO timestamp as a short relative age such as 3d ago."""
    if not timestamp:
        return ""
    then = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    for size, unit in ((31_536_000, "y"), (2_592_000, "mo"), (604_800, "w"), (86_400, "d"), (3_600, "h"), (60, "m")):
        if seconds >= size:
            return str(int(seconds // size)) + unit + " ago"
    return "just now"


def breakable(name):
    """Allow long names and words to wrap inside a grid cell at - _ . , and / boundaries."""
    for sep in ("-", "_", ".", ",", "/"):
        name = name.replace(sep, sep + "\u200b")
    # Also allow breaks inside CamelCase words such as CanonicalChromeExtension
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", "\u200b", name)
    # Finally break any remaining run longer than 12 characters (e.g. synologydownloadassistant)
    return re.sub(r"[^\s\u200b]{12}(?=[^\s\u200b]{3})", lambda m: m.group(0) + "\u200b", name)


# Proper nouns in repo descriptions that codespell flags as typos. Encoding one
# letter as an HTML entity renders identically on GitHub.
SPELLING_FALSE_POSITIVES = {"Hev" + "y": "Hev&#121;"}  # split so codespell skips the key


def html_escape(text):
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for word, encoded in SPELLING_FALSE_POSITIVES.items():
        text = text.replace(word, encoded)
    return text


REPOS_GRAPHQL = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: OWNER
      orderBy: {field: PUSHED_AT, direction: DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        description
        url
        isArchived
        isFork
        isPrivate
        createdAt
        updatedAt
        pushedAt
        stargazerCount
        forkCount
        primaryLanguage { name }
        defaultBranchRef { name }
        logo: object(expression: "HEAD:.github/logo.png") { id }
        openIssueCount: issues(states: OPEN) { totalCount }
        licenseInfo { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


class DiskCache:
    """Cache of API responses that expires after a number of hours."""

    def __init__(self, path=CACHE_FILE, ttl_hours=CACHE_TTL_HOURS):
        self.path = path
        self.ttl_seconds = ttl_hours * 3600
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        now = time.time()
        self.data = {k: v for k, v in self.data.items() if now - v.get("t", 0) <= self.ttl_seconds}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, sort_keys=True, indent=2)

    def get(self, key):
        entry = self.data.get(key)
        if entry is None:
            return None
        cached_at = entry.get("t", 0)
        if time.time() - cached_at > self.ttl_seconds:
            return None
        return entry.get("v")

    def set(self, key, value):
        self.data[key] = {"t": time.time(), "v": value}


class PermanentCache:
    """Cache with no expiry — for data that never changes (e.g. first commit dates)."""

    def __init__(self, path=PERMANENT_CACHE_FILE):
        self.path = path
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, sort_keys=True, indent=2)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class UpdaterError(Exception):
    """Raised when part of the profile README cannot be generated."""


class SearchIncompleteError(UpdaterError):
    """Raised when GitHub search keeps returning incomplete results."""


@dataclass
class ProfileData:
    """Everything gathered from GitHub while building the README."""

    total_lines: int = 0
    total_lines_lang: dict = field(default_factory=dict)
    repo_languages: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    prs: list = field(default_factory=list)
    recent_activity: list = field(default_factory=list)
    gist_count: int = 0


def graphql_node_to_repo(node):
    return {
        "name": node["name"],
        "description": node.get("description") or "",
        "html_url": node["url"],
        "stargazers_count": node.get("stargazerCount", 0),
        "forks_count": node.get("forkCount", 0),
        "fork": node.get("isFork", False),
        "archived": node.get("isArchived", False),
        "created_at": node.get("createdAt", ""),
        "updated_at": node.get("updatedAt", ""),
        "pushed_at": node.get("pushedAt", ""),
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "open_issues_count": (node.get("openIssueCount") or {}).get("totalCount", 0),
        "default_branch": (node.get("defaultBranchRef") or {}).get("name") or "main",
        "has_logo": node.get("logo") is not None,
        "license": ({"name": (node.get("licenseInfo") or {}).get("name")} if node.get("licenseInfo") else None),
    }


def recent_event_link(recent, _commit_url_lookup=None):
    """Return (url, title) for an event shown in recent activity, or None to skip it.

    Branch/tag create and delete events are noise and are skipped.
    """
    payload = recent["payload"]
    kind = recent["type"]
    repo_url = "https://github.com/" + recent["repo"]["name"]
    link = None
    if kind in ("IssueCommentEvent", "IssuesEvent") and "html_url" in payload.get("issue", {}):
        issue = payload["issue"]
        link = (issue["html_url"], issue.get("title") or "Issue")
    elif kind == "PullRequestEvent" and "html_url" in payload.get("pull_request", {}):
        pull_request = payload["pull_request"]
        link = (pull_request["html_url"], pull_request.get("title") or "Pull request")
    elif kind == "PushEvent":
        ref = (payload.get("ref") or "").replace("refs/heads/", "")
        commits = payload.get("commits") or []
        title = commits[-1]["message"].split("\n")[0] if commits else "Pushed to " + ref
        link = (repo_url + "/commits/" + ref, title)
    elif kind == "CreateEvent" and payload.get("ref_type") == "repository":
        link = (repo_url, "Created repository")
    elif kind == "ReleaseEvent" and "release" in payload:
        release = payload["release"]
        link = (release.get("html_url", repo_url), "Released " + (release.get("tag_name") or ""))
    return link


class ReadmeUpdater:
    """Builds the profile README.md from config.json, template.md and the GitHub API."""

    config_file = "config.json"

    def __init__(self):
        self.config = None
        self.template = None
        self.repos = None
        self.token = os.getenv("ghtoken") or os.getenv("GITHUB_TOKEN")
        self.data = ProfileData()
        self.cache = DiskCache()
        self.perm_cache = PermanentCache()
        self.read_config()
        self.read_template()
        if self.get_repos() is False:
            self.log("Rate limited")
            return
        self.generate_readme()
        self.cache.save()
        self.perm_cache.save()

    @staticmethod
    def log(message):
        print("Updater: " + message)

    def read_config(self):
        try:
            with open(self.config_file, encoding="utf-8") as config:
                self.config = json.loads(config.read())
            self.log("Got config")
            return True
        except (OSError, ValueError):
            return False

    def read_template(self):
        try:
            with open(self.config["template_file"], encoding="utf-8") as template:
                self.template = template.read()
            self.log("Got template file")
            self.log(self.template)
            return True
        except Exception as e:
            raise UpdaterError("Failed reading config") from e

    def web_request_retry(self, url, headers=None):
        retries = 3

        if headers is None:
            headers = {"Authorization": "token " + self.token} if self.token else {}

        try:
            time.sleep(0.5)
            while retries > 0:
                r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                if r.status_code == requests.codes.ok:
                    return r
                self.log("Not 200 for: " + url)
                retries = retries - 1
        except requests.RequestException as e:
            retries = retries - 1
            time.sleep(5 * retries)
            self.log(str(e))

        return False

    @staticmethod
    def _slim_cache_data(url, data):
        """Strip cached API responses to only the keys the code actually uses."""
        if data is None:
            return data
        if "/issues?" in url or "/pulls?" in url:
            # issues/PRs: only need html_url, title, updated_at, url, pull_request (presence check)
            if isinstance(data, list):
                keys = ("html_url", "title", "updated_at", "url", "pull_request")
                return [{k: item[k] for k in keys if k in item} for item in data]
        elif url.endswith("/actions/workflows") and isinstance(data, dict):
            keys = ("name", "path", "state")
            return {"workflows": [{k: w[k] for k in keys if k in w} for w in data.get("workflows", [])]}
        elif "/gists" in url:
            # gists: only need html_url, description, updated_at and file names
            if isinstance(data, list):
                keys = ("html_url", "description", "updated_at")
                return [
                    {**{k: item[k] for k in keys if k in item}, "files": {f: {} for f in item.get("files") or {}}}
                    for item in data
                ]
        elif ("/commits/" in url or "/git/commits/" in url) and isinstance(data, dict):
            # commit lookups: only need html_url
            return {k: data[k] for k in ("html_url",) if k in data}
        return data

    def web_request_retry_cached(self, url, headers=None):
        cached = self.cache.get(url)
        if cached is not None:
            self.log("Cache hit: " + url)
            return cached
        r = self.web_request_retry(url, headers)
        if r is not False:
            data = self._slim_cache_data(url, r.json())
            self.cache.set(url, data)
            return data
        return None

    def fetch_graphql(self, query, variables):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "bearer " + self.token
        payload = json.dumps({"query": query, "variables": variables})
        for attempt in range(3):
            try:
                time.sleep(0.5)
                r = requests.post(
                    self.config["graphql_url"],
                    headers=headers,
                    data=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                if r.status_code == requests.codes.ok:
                    body = r.json()
                    if "errors" in body:
                        self.log("GraphQL errors: " + str(body["errors"]))
                        return None
                    return body.get("data")
                self.log("GraphQL HTTP " + str(r.status_code) + " (attempt " + str(attempt + 1) + ")")
            except (requests.RequestException, ValueError) as e:
                self.log("GraphQL error: " + str(e) + " (attempt " + str(attempt + 1) + ")")
            time.sleep(1)
        return None

    def get_first_commit_date_http(self, repo):
        cache_key = "first_commit:" + repo
        cached = self.perm_cache.get(cache_key)
        if cached is not None:
            self.log("Permanent cache hit for first commit: " + repo)
            return cached

        next_url = None

        url = self.config["user_repos_url"] + "/" + repo + "/commits?sha=main&per_page=1&page=1"
        self.log(url)
        r = self.web_request_retry(url)
        if r is not False and "link" in r.headers:
            parts = r.headers["link"].split("<")
            if len(parts) > 2:
                next_url = parts[2].split(">")[0]

        if next_url is not None:
            r = self.web_request_retry(next_url)
            if r is not False:
                year = r.json()[0]["commit"]["author"]["date"].split("-")[0]
                self.log(year)
                self.perm_cache.set(cache_key, year)
                return year

        self.log("failed")
        return ""

    def _fetch_repo_nodes(self):
        """Return every repo node from GraphQL, or None if GraphQL failed."""
        cursor = None
        all_nodes = []
        while True:
            self.log("GraphQL repos page (cursor=" + str(cursor is not None) + ")")
            data = self.fetch_graphql(REPOS_GRAPHQL, {"login": self.config["user"], "cursor": cursor})
            if not data:
                return None
            repos_data = data["user"]["repositories"]
            all_nodes.extend(repos_data["nodes"])
            if not repos_data["pageInfo"]["hasNextPage"]:
                return all_nodes
            cursor = repos_data["pageInfo"]["endCursor"]

    def get_repos(self):
        try:
            all_nodes = self._fetch_repo_nodes()
            if all_nodes is None:
                # The REST API has no language sizes, logo or default-branch data, so a REST
                # fallback would publish an empty language section. Keep the last README instead.
                self.log("GraphQL failed, keeping the existing README")
                return False

            self.repos = []
            self.data.repo_languages = {}
            langs_agg = defaultdict(int)

            for node in all_nodes:
                # Never list private repos on the public profile
                if node.get("isPrivate", False):
                    continue
                repo = graphql_node_to_repo(node)
                self.repos.append(repo)

                # Store per-repo language data
                repo_langs = {}
                for edge in (node.get("languages") or {}).get("edges", []):
                    repo_langs[edge["node"]["name"]] = edge["size"]
                self.data.repo_languages[node["name"]] = repo_langs

                # Aggregate languages — skip forks and archived repos
                if not repo["fork"] and not repo["archived"]:
                    for lang_name, lang_bytes in repo_langs.items():
                        langs_agg[lang_name] += lang_bytes
                        self.data.total_lines += lang_bytes

            self.data.total_lines_lang = dict(langs_agg)

            self.repos.sort(key=lambda x: x["updated_at"], reverse=True)
            self.log(
                "Got repos via GraphQL: "
                + str(len(self.repos))
                + ", Languages: "
                + str(len(self.data.total_lines_lang))
                + ", LoC: "
                + str(self.data.total_lines)
            )
            return True
        except Exception as e:
            self.log("GraphQL get_repos error: " + str(e))
            raise UpdaterError("Failed reading repos") from e

    def _showcase_repos(self):
        """Public, non-fork, non-archived repos, most recently pushed first."""
        repos = [r for r in self.repos if not r.get("fork") and not r.get("archived")]
        return sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True)

    def _logo_url(self, repo):
        if repo.get("has_logo"):
            return (
                "https://raw.githubusercontent.com/"
                + self.config["user"]
                + "/"
                + repo["name"]
                + "/"
                + repo.get("default_branch", "main")
                + "/.github/logo.png"
            )
        return PROFILE_LOGO

    def _render_card(self, card_template, repo, desc_limit):
        name = repo["name"]
        stars = repo.get("stargazers_count", 0)
        language = repo.get("language") or ""
        replacements = {
            "{html_url}": repo["html_url"],
            "{logo_url}": self._logo_url(repo),
            "{name}": name,
            "{display_name}": breakable(name),
            "{description}": html_escape(breakable(shorten(repo.get("description"), desc_limit))),
            "{lang_dot}": ("<img src='" + self._dot_url(language) + "' width='10' height='10'/> " if language else ""),
            "{language}": language,
            "{stars}": ("★ " + str(stars)) if stars else "",
            "{year}": (repo.get("created_at") or "")[:4],
            "{badge_html}": self._badge_html(repo),
        }
        card = card_template
        for key, value in replacements.items():
            card = card.replace(key, value)
        return card

    def _ci_workflow(self, name):
        """Return the repo's main CI workflow from the workflows API, or None when it has none."""
        data = self.web_request_retry_cached(self.config["user_repos_url"] + "/" + name + "/actions/workflows")
        workflows = [
            w
            for w in (data or {}).get("workflows", [])
            if w.get("state") == "active" and w.get("path", "").startswith(".github/workflows/")
        ]
        if not workflows:
            return None
        for preferred in (".github/workflows/main.yml", ".github/workflows/main.yaml"):
            for workflow in workflows:
                if workflow["path"] == preferred:
                    return workflow
        for workflow in workflows:
            if workflow.get("name", "").upper() in ("CICD", "CI"):
                return workflow
        return workflows[0]

    def _badge_html(self, repo):
        workflow = self._ci_workflow(repo["name"])
        if workflow is None:
            return ""
        file_name = workflow["path"].rsplit("/", 1)[-1]
        actions_url = repo["html_url"] + "/actions/workflows/" + file_name
        badge = actions_url + "/badge.svg"
        return "<br/><a href='" + actions_url + "'><img src='" + badge + "' alt='CI'/></a>"

    @staticmethod
    def _dot_url(language):
        colour = lang_colour(language).lstrip("#")
        return "https://img.shields.io/badge/-%20-" + colour + "?style=flat-square"

    def _render_grid(self, tag, repos, per_row, desc_limit):
        pattern = "<" + tag + ">(.*)</" + tag + ">"
        card_template = re.search(pattern, self.template, flags=RE_FLAGS).group(1).strip()
        cells = ""
        for i, repo in enumerate(repos, start=1):
            cells += self._render_card(card_template, repo, desc_limit) + "\n"
            if i % per_row == 0 and i != len(repos):
                cells += "</tr><tr>\n"
        self.template = re.sub(pattern, lambda _m: cells, self.template, flags=RE_FLAGS)

    def generate_repos(self):
        try:
            repos = self._showcase_repos()
            for fetched, repo in enumerate(repos, start=1):
                repo["get_first_commit_date"] = self.get_first_commit_date_http(repo["name"])
                if fetched % 20 == 0:
                    self.perm_cache.save()
            self.perm_cache.save()
            self._render_grid("featured", self._featured_repos(repos), 3, 90)
            self._render_year_sections(repos)
            self.template = self.template.replace("{repo_count}", str(len(repos)))
        except Exception as e:
            self.log(str(e))
            raise UpdaterError("Failed generating repo grid") from e

    def _featured_repos(self, repos):
        by_name = {r["name"]: r for r in repos}
        featured = [by_name[n] for n in self.config.get("featured", []) if n in by_name]
        top = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:FEATURED_COUNT]
        return featured + [r for r in top if r not in featured]

    def _render_year_sections(self, repos):
        section_template, saved, sections = self._item_template("years"), self.template, ""
        by_year = defaultdict(list)
        for repo in sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True):
            by_year[repo["created_at"][:4]].append(repo)
        for year in sorted(by_year, reverse=True):
            self.template = section_template.replace("{section_year}", year)
            self.template = self.template.replace("{section_count}", str(len(by_year[year])))
            self._render_grid("repos", by_year[year], 3, 60)
            sections += self.template + "\n"
        self.template = saved
        self._fill("years", sections.rstrip("\n"))

    def _fill(self, tag, html):
        self.template = re.sub("<" + tag + ">(.*)</" + tag + ">", lambda _m: html, self.template, flags=RE_FLAGS)

    def _item_template(self, tag):
        return re.search("<" + tag + ">(.*)</" + tag + ">", self.template, flags=RE_FLAGS).group(1).strip()

    @staticmethod
    def _repo_and_number(url):
        parts = url.split("/")
        return parts[3] + "/" + parts[4], parts[-1]

    def _search_once(self, query):
        items = []
        total = 0
        for page in range(1, 11):
            url = "https://api.github.com/search/issues?per_page=100&page=" + str(page) + "&q=" + query
            res = self.web_request_retry(url)
            if res is False:
                return None
            body = res.json()
            total = body.get("total_count", 0)
            batch = body.get("items", [])
            items.extend(batch)
            if len(batch) < 100:
                break
        return items, total

    def _search(self, query):
        """Return every item matching a GitHub issue search query.

        The search API intermittently returns too few (or zero) items, so retry until the
        item count matches total_count; raise rather than publish a wrong count.
        """
        for attempt in range(SEARCH_ATTEMPTS):
            result = self._search_once(query)
            if result is not None:
                items, total = result
                final = attempt == SEARCH_ATTEMPTS - 1
                if len(items) >= min(total, 1000) and (items or final):
                    return sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)
            self.log("Search incomplete for " + query + " (attempt " + str(attempt + 1) + ")")
            time.sleep(5 * (attempt + 1))
        raise SearchIncompleteError("Search results incomplete for " + query)

    def _fill_section(self, tag, prefix, rows, more_url):
        """Fill a top-area list: the first LIST_LIMIT rows, a "more" link, the count and the latest item."""
        template = self._item_template(tag)
        html = ""
        for row in rows[:LIST_LIMIT]:
            item = template
            for key, value in row.items():
                item = item.replace("{" + key + "}", value)
            html += item + "\n"
        if len(rows) > LIST_LIMIT:
            html += (
                "<tr><td></td><td><a href='"
                + more_url
                + "'>+"
                + str(len(rows) - LIST_LIMIT)
                + " more</a></td><td></td></tr>\n"
            )
        self._fill(tag, html)
        latest = shorten(rows[0]["title_raw"], 26) if rows else "none yet"
        icon, title = TILES[prefix]
        os.makedirs("generated/tiles", exist_ok=True)
        with open("generated/tiles/" + prefix + ".svg", "w", encoding="utf-8") as f:
            f.write(svg_tile(icon, title, str(len(rows)) + " · " + shorten(rows[0]["title_raw"], 17) if rows else "0"))
        self.template = self.template.replace("{" + prefix + "_link}", more_url)
        self.template = self.template.replace("{" + prefix + "_count}", str(len(rows)))
        self.template = self.template.replace("{" + prefix + "_latest}", html_escape(latest))
        self.template = self.template.replace("{" + prefix + "_latest_rel}", rows[0]["rel"] if rows else "")

    def _item_rows(self, items, icon):
        rows = []
        for item in items:
            repo_name, number = self._repo_and_number(item["html_url"])
            rows.append(
                {
                    "icon": icon,
                    "url": item["html_url"],
                    "title": html_escape(shorten(item["title"], 70)),
                    "title_raw": item["title"],
                    "tag": html_escape(repo_name.split("/")[1] + "#" + number),
                    "rel": relative_time(item.get("updated_at", "")),
                }
            )
        return rows

    def generate_issues(self):
        try:
            user = self.config["user"]
            self.data.issues = self._search("user:" + user + "+is:issue+is:open+archived:false")
            self._fill_section(
                "issues",
                "issue",
                self._item_rows(self.data.issues, "🟢"),
                "https://github.com/issues?q=is%3Aissue+is%3Aopen+archived%3Afalse+user%3A" + user,
            )
        except (AttributeError, KeyError, TypeError, IndexError) as e:
            raise UpdaterError("Failed generating issues") from e

    def generate_prs(self):
        try:
            user = self.config["user"]
            self.data.prs = self._search("author:" + user + "+is:pr+is:open")
            self._fill_section(
                "prs",
                "pr",
                self._item_rows(self.data.prs, "🔀"),
                "https://github.com/pulls?q=is%3Apr+is%3Aopen+author%3A" + user,
            )
        except (AttributeError, KeyError, TypeError, IndexError) as e:
            raise UpdaterError("Failed generating prs") from e

    def generate_recent_activity(self):
        try:
            res = self.web_request_retry(self.config["events_url"])
            events = res.json() if res is not False else []
            rows = []
            for recent in events:
                link = recent_event_link(recent)
                if link is None:
                    continue
                rows.append(
                    {
                        "icon": RECENT_ICONS.get(recent["type"], "•"),
                        "url": link[0],
                        "title": html_escape(shorten(link[1], 70)),
                        "title_raw": link[1],
                        "tag": html_escape(recent["repo"]["name"].split("/")[-1]),
                        "rel": relative_time(recent["created_at"]),
                    }
                )
            self.data.recent_activity = events
            self._fill_section("recent", "activity", rows, self.config["github_url"])
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            raise UpdaterError("Failed generating activity") from e

    def generate_gists(self):
        try:
            gists = self.web_request_retry_cached(self.config["gists_url"]) or []
            gists = sorted(gists, key=lambda g: g.get("updated_at") or "", reverse=True)
            self.data.gist_count = len(gists)
            rows = []
            for gist in gists:
                files = list(gist.get("files") or {})
                title = gist.get("description") or (files[0] if files else "Untitled gist")
                rows.append(
                    {
                        "icon": "📄",
                        "url": gist["html_url"],
                        "title": html_escape(shorten(title, 70)),
                        "title_raw": title,
                        "tag": html_escape(shorten(files[0], 30) if files else "gist"),
                        "rel": relative_time(gist.get("updated_at") or ""),
                    }
                )
            self._fill_section("gists", "gist", rows, "https://gist.github.com/" + self.config["user"])
            return True
        except Exception as e:
            raise UpdaterError("Failed generating gists") from e

    def _avatar_data_uri(self, avatar_url):
        """Fetch a small avatar and return it as a data URI so the button SVG is self-contained."""
        try:
            r = requests.get(avatar_url, timeout=REQUEST_TIMEOUT)
            if r.status_code == requests.codes.ok:
                kind = r.headers.get("content-type", "image/png").split(";")[0]
                return "data:" + kind + ";base64," + base64.b64encode(r.content).decode("ascii")
        except requests.RequestException as e:
            self.log("Avatar fetch failed: " + str(e))
        return ""

    def generate_orgs(self):
        try:
            orgs_template = self._item_template("orgs")
            os.makedirs("generated/orgs", exist_ok=True)
            orgs = ""
            for url, name in self.config["organizations"]:
                login = url.rstrip("/").split("/")[-1]
                res = self.web_request_retry("https://api.github.com/users/" + login)
                info = res.json() if res is not False else {}
                kind = "forks" if "fork" in login.lower() else "repos"
                count = (str(info["public_repos"]) + " " + kind) if "public_repos" in info else kind
                avatar = self._avatar_data_uri(
                    (info.get("avatar_url") or "https://github.com/" + login + ".png") + "&s=64"
                )
                path = "generated/orgs/" + login + ".svg"
                with open(path, "w", encoding="utf-8") as f:
                    f.write(svg_org_button(name, count, avatar))
                item = orgs_template.replace("{org_url}", url).replace("{org_name}", html_escape(name))
                orgs += item.replace("{org_button}", path).replace("{org_count}", count) + "\n"
            self._fill("orgs", orgs)
            return True
        except Exception as e:
            raise UpdaterError("Failed generating org list") from e

    def _top_languages(self):
        return sorted(self.data.total_lines_lang.items(), key=itemgetter(1), reverse=True)[:TOP_LANGUAGES]

    def favorite_langs(self):
        langs_template = self._item_template("langs")
        top = self._top_languages()
        total = sum(self.data.total_lines_lang.values()) or 1
        output = ""
        for i, (lang, size) in enumerate(top, start=1):
            col = langs_template.replace("{language}", lang)
            col = col.replace("{lang_dot}", "<img src='" + self._dot_url(lang) + "' width='10' height='10'/>")
            col = col.replace("{bytes_human}", human_bytes(size))
            output += col.replace("{percent}", f"{size / total * 100:.1f}") + "\n"
            if i % 5 == 0 and i != len(top):
                output += "</tr><tr>\n"
        self._fill("langs", output)

    def generate_svgs(self):
        os.makedirs("generated", exist_ok=True)

        with open("generated/timeline.svg", "w", encoding="utf-8") as f:
            f.write(svg_timeline(self._showcase_repos()))
        with open("generated/languages_bar.svg", "w", encoding="utf-8") as f:
            f.write(svg_languages_bar(self._top_languages()))
        self.log("Wrote generated/timeline.svg and generated/languages_bar.svg")

    def generate_readme(self):
        if not self.data.total_lines_lang:
            self.log("No language data, keeping the existing README")
            return False
        try:
            self.generate_orgs()
            self.generate_repos()
            self.favorite_langs()
            self.generate_prs()
            self.generate_issues()
            self.generate_gists()
            self.generate_recent_activity()
            self.generate_svgs()

            replacements = {
                "{github_url}": self.config["github_url"],
                "{linkedin_url}": self.config["linkedin_url"],
                "{last_updated_safe}": datetime.now().astimezone().strftime("%Y--%m--%d"),
            }
            for key, value in replacements.items():
                self.template = self.template.replace(key, value)

            self.log(self.template)

            with open("README.md", "w", encoding="utf-8") as f:
                f.write(self.template)
            return True

        except SearchIncompleteError as e:
            self.log(str(e) + ", keeping the existing README")
            return False

        except Exception as e:
            raise UpdaterError("Failed generating readme") from e


if __name__ == "__main__":
    ReadmeUpdater()
