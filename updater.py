import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
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
    max_year = max(*year_counts, datetime.now().year)
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
TOP_LANGUAGES = 12
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


def shorten(text, limit):
    text = (text or "").strip().replace("|", "-")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def breakable(name):
    """Allow long repo names to wrap inside a grid cell at - _ and . boundaries."""
    for sep in ("-", "_", "."):
        name = name.replace(sep, sep + "\u200b")
    return name


def html_escape(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
                self.log("GraphQL failed, falling back to REST")
                return self._get_repos_rest()

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

    def _get_repos_rest(self):
        """Fallback REST-based repo fetching."""
        try:
            page = 1
            self.repos = []
            while True:
                url = self.config["repos_url"] + "&page=" + str(page)
                self.log(url)
                r = self.web_request_retry(url)
                if r is False:
                    return False
                self.log("got page " + str(page))
                res = r.json()

                if len(res) == 0:
                    self.log("no repos, break")
                    break

                # Never list private repos on the public profile
                self.repos = self.repos + [x for x in res if not x.get("private", False)]
                page += 1

            self.repos.sort(key=lambda x: x["updated_at"], reverse=True)
            self.log("Got repos via REST")
            return True
        except Exception as e:
            raise UpdaterError("Failed reading repos") from e

    def _get_repo_items(self, repo, kind, label):
        try:
            url = self.config["user_repos_url"] + "/" + repo + "/" + kind + "?state=open"
            self.log(url)
            data = self.web_request_retry_cached(url)
            if data is None:
                self.log("No data for " + kind + ": " + repo)
            return data
        except Exception as e:
            raise UpdaterError("Failed reading " + label) from e

    def _collect_issues_and_prs(self, repo):
        # Skip issues/PRs fetch for repos with 0 open issues
        if repo.get("open_issues_count", 0) <= 0:
            return
        repo_issues = self._get_repo_items(repo["name"], "issues", "issues")
        repo_prs = self._get_repo_items(repo["name"], "pulls", "pull requests")

        for item in repo_issues or []:
            if "pull_request" in item:
                if item not in self.data.prs:
                    self.data.prs.append(item)
            else:
                self.data.issues.append(item)

        for item in repo_prs or []:
            if not any(p["html_url"] == item["html_url"] for p in self.data.prs):
                self.data.prs.append(item)

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
            "{description}": html_escape(shorten(repo.get("description"), desc_limit)),
            "{lang_dot}": ("<img src='" + self._dot_url(language) + "' width='10' height='10'/> " if language else ""),
            "{language}": language,
            "{stars}": ("★ " + str(stars)) if stars else "",
            "{badge}": self.config["user_url"] + name + "/actions/workflows/main.yml/badge.svg",
            "{actions_url}": repo["html_url"] + "/actions",
        }
        card = card_template
        for key, value in replacements.items():
            card = card.replace(key, value)
        return card

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
                self._collect_issues_and_prs(repo)
            self.perm_cache.save()

            featured = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:FEATURED_COUNT]
            self._render_grid("featured", featured, 3, 90)
            self._render_grid("repos", repos, 4, 60)
            self.template = self.template.replace("{repo_count}", str(len(repos)))
        except Exception as e:
            self.log(str(e))
            raise UpdaterError("Failed generating repo grid") from e

    def _fill(self, tag, html):
        self.template = re.sub("<" + tag + ">(.*)</" + tag + ">", lambda _m: html, self.template, flags=RE_FLAGS)

    def _item_template(self, tag):
        return re.search("<" + tag + ">(.*)</" + tag + ">", self.template, flags=RE_FLAGS).group(1).strip()

    @staticmethod
    def _repo_and_number(url):
        parts = url.split("/")
        return parts[3] + "/" + parts[4], parts[-1]

    def _generate_item_list(self, tag, items, prefix):
        item_template = self._item_template(tag)
        items = sorted(items, key=lambda x: x.get("updated_at", ""), reverse=True)
        html = ""
        for item in items:
            repo_name, number = self._repo_and_number(item["html_url"])
            row = item_template.replace("{" + prefix + "_url}", item["html_url"])
            row = row.replace("{" + prefix + "_title}", html_escape(item["title"]))
            row = row.replace("{" + prefix + "_repo}", repo_name)
            row = row.replace("{" + prefix + "_number}", number)
            html += row.replace("{updated_at}", item.get("updated_at", "").split("T")[0]) + "\n"
        self._fill(tag, html)
        self.template = self.template.replace("{" + prefix + "_count}", str(len(items)))

    def generate_issues(self):
        try:
            self._generate_item_list("issues", self.data.issues, "issue")
        except (AttributeError, KeyError, TypeError) as e:
            raise UpdaterError("Failed generating issues") from e

    def generate_prs(self):
        try:
            self._generate_item_list("prs", self.data.prs, "pr")
        except (AttributeError, KeyError, TypeError) as e:
            raise UpdaterError("Failed generating prs") from e

    def generate_recent_activity(self):
        try:
            res = self.web_request_retry(self.config["events_url"])
            events = res.json() if res is not False else []
            recent_template = self._item_template("recent")
            html = ""
            shown = 0
            for recent in events:
                link = recent_event_link(recent)
                if link is None:
                    continue
                row = recent_template.replace("{recent_activity_url}", link[0])
                row = row.replace("{recent_activity_title}", html_escape(shorten(link[1], 100)))
                row = row.replace("{recent_repo}", recent["repo"]["name"])
                row = row.replace("{recent_icon}", RECENT_ICONS.get(recent["type"], "•"))
                row = row.replace("{recent_at}", recent["created_at"][:16].replace("T", " "))
                html += row + "\n"
                shown += 1
            self.data.recent_activity = events
            self._fill("recent", html)
            self.template = self.template.replace("{activity_count}", str(shown))
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            raise UpdaterError("Failed generating activity") from e

    def generate_gists(self):
        try:
            gists = self.web_request_retry_cached(self.config["gists_url"]) or []
            self.data.gist_count = len(gists)
            gists_template = self._item_template("gists")
            html = ""
            for gist in gists:
                files = ", ".join(list(gist.get("files") or {})[:3])
                title = gist.get("description") or files or "Untitled gist"
                row = gists_template.replace("{gist_url}", gist["html_url"])
                row = row.replace("{gist_title}", html_escape(title))
                row = row.replace("{gist_files}", html_escape(files))
                html += row.replace("{updated_at}", (gist.get("updated_at") or "").split("T")[0]) + "\n"
            self._fill("gists", html)
            return True
        except Exception as e:
            raise UpdaterError("Failed generating gists") from e

    def generate_orgs(self):
        try:
            orgs_template = self._item_template("orgs")
            orgs = ""
            for org in self.config["organizations"]:
                orgs += orgs_template.replace("{org_url}", org[0]).replace("{org_name}", org[1]) + "\n"
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
            if i % 4 == 0 and i != len(top):
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
                "{gist_count}": str(self.data.gist_count),
            }
            for key, value in replacements.items():
                self.template = self.template.replace(key, value)

            self.log(self.template)

            with open("README.md", "w", encoding="utf-8") as f:
                f.write(self.template)
            return True

        except Exception as e:
            raise UpdaterError("Failed generating readme") from e


if __name__ == "__main__":
    ReadmeUpdater()
