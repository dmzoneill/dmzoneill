import json
import os
import pprint
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


def svg_timeline(repos, width=760, height=140):
    year_counts = _count_years(repos)

    if not year_counts:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"/>'

    min_year = min(year_counts)
    max_year = max(year_counts)
    if min_year == max_year:
        max_year = min_year + 1
    max_count = max(year_counts.values())

    left = 60
    right = width - 40
    line_y = height // 2 + 5
    span = right - left

    elements = f'  <line x1="{left}" y1="{line_y}" x2="{right}" y2="{line_y}" stroke="#30363d" stroke-width="1.5"/>\n'

    for year, count in sorted(year_counts.items()):
        elements += _timeline_marker(
            left + (year - min_year) / (max_year - min_year) * span,
            line_y,
            5 + (count / max_count) * 18,
            year,
            count,
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    .card   {{ fill: #0d1117; stroke: #30363d; stroke-width: 1; }}
    .head   {{ font: bold 14px {FONT}; fill: #58a6ff; }}
    .tyear  {{ font: bold 10px {FONT}; fill: #484f58; }}
    .tcount {{ font: bold 11px {FONT}; fill: #8b949e; }}
    @media (prefers-color-scheme: light) {{
      .card   {{ fill: #ffffff; stroke: #d0d7de; }}
      .head   {{ fill: #0969da; }}
      .tyear  {{ fill: #57606a; }}
      .tcount {{ fill: #57606a; }}
    }}
  </style>
  <rect class="card" width="{width}" height="{height}" rx="8"/>
  <text class="head" x="30" y="25">Project Timeline</text>
{elements}
</svg>"""


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


def language_badge(config, lang):
    badge = config["badges"].get(lang, "")
    if badge == "":
        badge = "https://img.shields.io/badge/_-" + lang + " -11DDDD.svg?style=for-the-badge"
    return badge


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
        "license": ({"name": (node.get("licenseInfo") or {}).get("name")} if node.get("licenseInfo") else None),
    }


def recent_event_link(recent, commit_url_lookup):
    """Return (url, title) for an event shown in recent activity.

    Returns None to skip the event entirely, or False to count it without showing it.
    """
    payload = recent["payload"]
    kind = recent["type"]
    link = None
    if kind == "IssueCommentEvent" and "issue" in payload:
        issue = payload["issue"]
        link = (issue["html_url"], issue["title"]) if "html_url" in issue and "title" in issue else False
    elif kind == "PushEvent":
        commits = payload.get("commits", [])
        link = (commit_url_lookup(commits[0]["url"]), commits[0]["message"]) if commits else False
    elif kind == "CreateEvent":
        link = (recent["repo"]["url"], recent["repo"]["name"])
    elif kind == "PullRequestEvent" and "html_url" in payload.get("pull_request", {}):
        pull_request = payload["pull_request"]
        link = (pull_request["html_url"], pull_request["title"]) if "title" in pull_request else False
    return link


def year_header(last_year_header, count, details_open):
    close_prev = "</tbody></table></details>" if details_open else "</tbody></table>"
    return (
        close_prev
        + "<details><summary><strong>"
        + last_year_header
        + " ("
        + str(count)
        + " projects)</strong></summary>"
        + "<table width='100%' style='width:100%'><thead><tr><th>Project</th>"
        + "<th>View</th><th>Status</th></tr></thead><tbody>"
    )


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
            # gists: only need html_url, description
            if isinstance(data, list):
                return [{k: item[k] for k in ("html_url", "description") if k in item} for item in data]
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

    def get_repo_languages(self, name):
        try:
            languages = self.data.repo_languages.get(name)

            if not languages:
                # Fallback to REST if no GraphQL data
                languages_url = self.config["user_repos_url"] + "/" + name + "/languages"
                self.log(languages_url)
                languages = self.web_request_retry_cached(languages_url)
                if languages is None:
                    return False

            lines = sum(languages.values())
            if lines == 0:
                return False

            language = ""
            for lang, count in languages.items():
                if round(round(count / lines, 2) * 100) != 0:
                    badge = language_badge(self.config, lang)
                    language += "<img src='" + badge + "' title='" + lang + "' height='20px'/> "

            return language[0 : len(language) - 2]
        except Exception as e:
            raise UpdaterError("Failed reading languages") from e

    def _collect_issues_and_prs(self, repo):
        # Skip issues/PRs fetch for repos with 0 open issues
        if repo.get("open_issues_count", 0) <= 0:
            self.log("Skipping issues/PRs for " + repo["name"] + " (0 open issues)")
            return
        repo_issues = self._get_repo_items(repo["name"], "issues", "issues")
        repo_prs = self._get_repo_items(repo["name"], "pulls", "pull requests")

        for item in repo_issues or []:
            if "pull_request" in item:
                self.data.prs.append(item)
            else:
                self.data.issues.append(item)

        for item in repo_prs or []:
            if item not in self.data.prs:
                self.data.prs.append(item)

    def _render_repo_row(self, rows_template, repo):
        live = self.config["live"]
        language = self.get_repo_languages(repo["name"])
        language = language if language is not False else (repo["language"] or "")
        name = repo["name"]
        live_url = live[name][0] if name in live else ""
        live_name = live[name][1] if name in live else ""
        license_name = repo["license"]["name"] if repo["license"] is not None else ""
        updated_at = repo["updated_at"] if repo["updated_at"] is not None else ""
        badge = self.config["user_url"] + "/" + name + "/actions/workflows/main.yml/badge.svg"

        replacements = {
            "{language}": language,
            "{first_commit}": "(" + repo["get_first_commit_date"] + ")",
            "{html_url}": repo["html_url"],
            "{name}": name,
            "{live_url}": live_url,
            "{live_name}": live_name,
            "{license}": license_name,
            "{updated_at}": updated_at.split("T")[0],
            "{badge}": badge,
        }
        row = rows_template
        for key, value in replacements.items():
            row = row.replace(key, value)

        row = self.generate_issues(row, name)
        row = self.generate_recent_activity(row, name)
        row = self.generate_prs(row, name)
        return row, live_url != "" and live_name != ""

    def _split_repos(self):
        live_repos = []
        old_repos = []
        for fetched, repo in enumerate(self.repos, start=1):
            repo["get_first_commit_date"] = self.get_first_commit_date_http(repo["name"])
            self.log(repo["name"] + " -> " + repo["get_first_commit_date"])
            if fetched % 20 == 0:
                self.perm_cache.save()
            if repo["name"] in self.config["live"]:
                live_repos.append(repo)
            else:
                old_repos.append(repo)
        self.perm_cache.save()
        live_repos = sorted(live_repos, key=itemgetter("pushed_at"))
        old_repos = sorted(old_repos, key=itemgetter("get_first_commit_date"), reverse=True)
        return live_repos, old_repos

    def generate_repos(self):
        try:
            rows_template = re.search("<repos>(.*)</repos>", self.template, flags=RE_FLAGS).group(1).strip()
            rows = ""
            live = self.config["live"]

            self.log("generate_repos")
            live_repos, old_repos = self._split_repos()

            # Count repos per year for collapsed section headers
            year_counts = defaultdict(int)
            for repo in old_repos:
                if repo["get_first_commit_date"]:
                    year_counts[repo["get_first_commit_date"]] += 1

            last_year_header = ""
            details_open = False

            for repo in live_repos + old_repos:
                self._collect_issues_and_prs(repo)
                row, prepend = self._render_repo_row(rows_template, repo)

                if repo["name"] not in live and last_year_header != repo["get_first_commit_date"]:
                    last_year_header = repo["get_first_commit_date"]
                    count = year_counts.get(last_year_header, 0)
                    row = year_header(last_year_header, count, details_open) + row
                    details_open = True
                rows = row + "\n" + rows if prepend else rows + "\n" + row

            # Close the final <details> if one was opened
            if details_open:
                rows += "</details>"

            self.template = re.sub("<repos>(.*)</repos>", rows, self.template, flags=RE_FLAGS)
        except Exception as e:
            self.log(str(e))
            raise UpdaterError("Failed generating repo list") from e

    def _fill_list(self, template, repo, tag, html, heading):
        """Put rendered list html into the per-repo row, or into the README when repo is False."""
        pattern = "<ul><" + tag + ">(.*)</" + tag + "></ul>"
        if repo is False:
            self.template = re.sub(pattern, "<ul>" + html + "</ul>", self.template, flags=RE_FLAGS)
            return True
        prefix = "<h4>" + heading + "</h4><ul>" if heading else "<ul>"
        return re.sub(pattern, prefix + html + "</ul>", template, flags=RE_FLAGS)

    def _list_template(self, template, repo, tag):
        source = self.template if repo is False else template
        return re.search("<ul><" + tag + ">(.*)</" + tag + "></ul>", source, flags=RE_FLAGS).group(1).strip()

    def _generate_item_list(self, template, repo, spec):
        """Shared body of generate_issues and generate_prs."""
        tag, items, prefix, url_key, heading = spec
        item_template = self._list_template(template, repo, tag)
        html = ""
        added = 0
        for item in list(items):
            if repo is not False and added == 5:
                break
            if tag == "issues" and "pull" in item["html_url"]:
                continue
            if repo is False or self.config["user"] + "/" + str(repo) in item[url_key]:
                item_html = item_template.replace("{" + prefix + "_url}", item["html_url"])
                item_html = item_html.replace("{" + prefix + "_title}", item["title"])
                html += item_html.replace("{updated_at}", item["updated_at"].split("T")[0])
                added += 1
        if repo is False:
            self.template = self.template.replace("{" + prefix + "_count}", str(len(items)))
        return self._fill_list(template, repo, tag, html, heading if added > 0 else "")

    def generate_issues(self, template="", repo=False):
        try:
            spec = ("issues", self.data.issues, "issue", "html_url", "Issues")
            return self._generate_item_list(template, repo, spec)
        except (AttributeError, KeyError, TypeError) as e:
            self.log(str(e))
            if repo:
                return template
            raise UpdaterError("Failed generating issues") from e

    def generate_prs(self, template="", repo=False):
        try:
            spec = ("prs", self.data.prs, "pr", "url", "Pull Requests")
            return self._generate_item_list(template, repo, spec)
        except (AttributeError, KeyError, TypeError) as e:
            self.log(str(e))
            if repo:
                return template
            raise UpdaterError("Failed generating prs") from e

    def get_commit_html_url(self, url):
        try:
            data = self.web_request_retry_cached(url)
            if data is not None:
                return data["html_url"]
            return False
        except (KeyError, TypeError, ValueError):
            return url

    def generate_recent_activity(self, template="", repo=False):
        try:
            if len(self.data.recent_activity) == 0:
                res = self.web_request_retry(self.config["events_url"])
                if res is False:
                    return template if repo else False
                self.data.recent_activity = res.json()

            recent_template = self._list_template(template, repo, "recent")
            recent_html = ""
            num = 0
            for recent in self.data.recent_activity:
                if repo is not False and num == 5:
                    break

                self.log(
                    "generate_recent_activity "
                    + self.config["user"]
                    + "/"
                    + str(repo)
                    + " == "
                    + recent["repo"]["name"]
                )

                if repo is not False and self.config["user"] + "/" + str(repo) != recent["repo"]["name"]:
                    continue
                if recent["type"] == "PushEvent":
                    self.log(pprint.pformat(recent))
                link = recent_event_link(recent, self.get_commit_html_url)
                if link is None:
                    continue
                if link:
                    recent_html += recent_template.replace("{recent_activity_url}", link[0]).replace(
                        "{recent_activity_title}", link[1]
                    )
                num += 1

            heading = "Recent Activity" if recent_html else ""
            return self._fill_list(template, repo, "recent", recent_html, heading)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            self.log(str(e))
            if repo:
                return template
            raise UpdaterError("Failed generating activity") from e

    def generate_gists(self):
        try:
            gists = self.web_request_retry_cached(self.config["gists_url"])
            self.data.gist_count = len(gists) if gists else 0
            if gists is not None:
                gists_template = re.search("<gists>(.*)</gists>", self.template, flags=RE_FLAGS).group(1).strip()

                gists_html = ""
                for gist in gists:
                    gist_html = gists_template.replace("{gist_url}", gist["html_url"])
                    gists_html += gist_html.replace("{gist_title}", gist["description"])

                self.template = re.sub("<gists>(.*)</gists>", gists_html, self.template, flags=RE_FLAGS)
            return True
        except Exception as e:
            self.log(self.template)
            raise UpdaterError("Failed generating gists") from e

    def generate_orgs(self):
        try:
            orgs_template = re.search("<orgs>(.*)</orgs>", self.template, flags=RE_FLAGS).group(1).strip()

            orgs = ""
            for org in self.config["organizations"]:
                orgs += orgs_template.replace("{org_url}", org[0]).replace("{org_name}", org[1]) + "\n"

            self.template = re.sub("<orgs>(.*)</orgs>", orgs, self.template, flags=RE_FLAGS)
            return True
        except Exception as e:
            raise UpdaterError("Failed generating org list") from e

    def favorite_langs(self):
        langs_template = re.search("<langs>(.*)</langs>", self.template, flags=RE_FLAGS).group(1).strip()

        output = ""
        for i, (lang, lines) in enumerate(self.data.total_lines_lang.items(), start=1):
            badge = language_badge(self.config, lang)
            col = langs_template.replace(
                "{language}",
                "<img src='" + badge + "' title='" + lang + "'  height='20px'/>",
            )
            output += col.replace("{lines}", str(lines)) + "\n"
            if i % 4 == 0:
                output += "</tr><tr>\n"

        self.template = re.sub("<langs>(.*)</langs>", output, self.template, flags=RE_FLAGS)

    def generate_svgs(self):
        os.makedirs("generated", exist_ok=True)

        with open("generated/timeline.svg", "w", encoding="utf-8") as f:
            f.write(svg_timeline(self.repos))
        self.log("Wrote generated/timeline.svg")

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
                "{langcount}": str(len(self.data.total_lines_lang) + 1),
                "{last_updated}": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S"),
                "{activity_count}": str(len(self.data.recent_activity)),
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
