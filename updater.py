import json
import os
import pprint
import re
import time
from collections import defaultdict
from datetime import datetime
from operator import itemgetter

import requests

CACHE_FILE = "generated/cache.json"
CACHE_TTL_HOURS = 12
PERMANENT_CACHE_FILE = "generated/permanent_cache.json"

FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, "
    "sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji'"
)


def fmt(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def svg_stats(repos, stars, issues, prs, loc, lang_count, width=355, height=220):
    items = [
        ("Repositories", fmt(repos)),
        ("Stars Earned", fmt(stars)),
        ("Open Issues", fmt(issues)),
        ("Open PRs", fmt(prs)),
        ("Lines of Code", fmt(loc)),
        ("Languages", fmt(lang_count)),
    ]
    right = width - 30
    rows = ""
    for i, (label, value) in enumerate(items):
        y = 48 + i * 27
        delay = 0.1 * i
        rows += f"""    <g style="animation:slideIn .4s ease-out {delay:.1f}s both">
      <text x="30" y="{y}" class="label">{label}</text>
      <text x="{right}" y="{y}" class="value" text-anchor="end">{value}</text>
    </g>\n"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <style>
    @keyframes slideIn {{ from {{ opacity:0; transform:translateX(-10px) }} to {{ opacity:1; transform:translateX(0) }} }}
    .card  {{ fill: #0d1117; stroke: #30363d; stroke-width: 1; }}
    .head  {{ font: bold 14px {FONT}; fill: #58a6ff; }}
    .label {{ font: 13px {FONT}; fill: #8b949e; }}
    .value {{ font: bold 13px {FONT}; fill: #e6edf3; }}
    @media (prefers-color-scheme: light) {{
      .card  {{ fill: #ffffff; stroke: #d0d7de; }}
      .head  {{ fill: #0969da; }}
      .label {{ fill: #57606a; }}
      .value {{ fill: #1f2328; }}
    }}
  </style>
  <rect class="card" width="{width}" height="{height}" rx="8"/>
  <text class="head" x="30" y="28">GitHub Stats</text>
  <line x1="30" y1="35" x2="{right}" y2="35" stroke="#21262d" stroke-width="0.5"/>
{rows}</svg>"""


def svg_top_repos(repos, width=355, height=260):
    starred = sorted(
        [(r["name"], r.get("stargazers_count", 0)) for r in repos if r.get("stargazers_count", 0) > 0],
        key=lambda x: x[1],
        reverse=True,
    )[:10]
    if not starred:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"/>'

    max_stars = starred[0][1]
    bar_area_left = int(width * 0.45)
    bar_area_right = width - 20
    bar_area_w = bar_area_right - bar_area_left
    bar_h = 16
    row_h = 22
    top_pad = 40

    bars = ""
    for i, (name, stars) in enumerate(starred):
        y = top_pad + i * row_h
        w = (stars / max_stars) * bar_area_w if max_stars > 0 else 0
        color_idx = i % 8
        colors = ["#58a6ff", "#bc8cff", "#3fb950", "#f0883e", "#f778ba", "#79c0ff", "#d2a8ff", "#56d364"]
        color = colors[color_idx]
        display_name = name if len(name) <= 18 else name[:16] + ".."

        bars += (
            f'  <text x="{bar_area_left - 8}" y="{y + bar_h - 3}" class="rname" text-anchor="end">{esc(display_name)}</text>\n'
            f'  <rect x="{bar_area_left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="3" fill="{color}" opacity="0.85"/>\n'
            f'  <text x="{bar_area_left + w + 6:.1f}" y="{y + bar_h - 3}" class="scount">{stars}</text>\n'
        )

    actual_h = top_pad + len(starred) * row_h + 15
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{actual_h}" viewBox="0 0 {width} {actual_h}">
  <style>
    .card   {{ fill: #0d1117; stroke: #30363d; stroke-width: 1; }}
    .head   {{ font: bold 14px {FONT}; fill: #58a6ff; }}
    .rname  {{ font: 12px {FONT}; fill: #8b949e; }}
    .scount {{ font: bold 11px {FONT}; fill: #e6edf3; }}
    @media (prefers-color-scheme: light) {{
      .card   {{ fill: #ffffff; stroke: #d0d7de; }}
      .head   {{ fill: #0969da; }}
      .rname  {{ fill: #57606a; }}
      .scount {{ fill: #1f2328; }}
    }}
  </style>
  <rect class="card" width="{width}" height="{actual_h}" rx="8"/>
  <text class="head" x="30" y="28">Most Starred Repos</text>
  <line x1="30" y1="35" x2="{width - 30}" y2="35" stroke="#21262d" stroke-width="0.5"/>
{bars}
</svg>"""


def svg_timeline(repos, width=760, height=140):
    year_counts = defaultdict(int)
    for r in repos:
        y = r.get("first_commit_year") or r.get("get_first_commit_date") or r.get("created_at", "")[:4]
        if y and str(y).isdigit():
            year_counts[int(y)] += 1

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

    elements = ""
    elements += f'  <line x1="{left}" y1="{line_y}" x2="{right}" y2="{line_y}" stroke="#30363d" stroke-width="1.5"/>\n'

    for year, count in sorted(year_counts.items()):
        frac = (year - min_year) / (max_year - min_year)
        x = left + frac * span
        r = 5 + (count / max_count) * 18
        elements += (
            f'  <circle cx="{x:.1f}" cy="{line_y}" r="{r:.1f}" fill="#58a6ff" opacity="0.3"/>\n'
            f'  <circle cx="{x:.1f}" cy="{line_y}" r="{r * 0.6:.1f}" fill="#58a6ff" opacity="0.6"/>\n'
            f'  <circle cx="{x:.1f}" cy="{line_y}" r="{max(3, r * 0.3):.1f}" fill="#58a6ff"/>\n'
            f'  <text x="{x:.1f}" y="{line_y + r + 14:.1f}" class="tyear" text-anchor="middle">{year}</text>\n'
            f'  <text x="{x:.1f}" y="{line_y - r - 6:.1f}" class="tcount" text-anchor="middle">{count}</text>\n'
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
        url
        isArchived
        isFork
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
    def __init__(self, path=CACHE_FILE, ttl_hours=CACHE_TTL_HOURS):
        self.path = path
        self.ttl_seconds = ttl_hours * 3600
        self.data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        now = time.time()
        self.data = {
            k: v for k, v in self.data.items()
            if now - v.get("t", 0) <= self.ttl_seconds
        }
        with open(self.path, "w") as f:
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
            with open(self.path, "r") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, sort_keys=True, indent=2)

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class ReadmeUpdater:
    config_file = "config.json"
    config = None
    template = None
    repos = None
    token = os.getenv("ghtoken") or os.getenv("GITHUB_TOKEN")
    total_lines = 0
    total_lines_lang = {}  # type: ignore
    repo_languages = {}  # type: ignore
    issues = []
    issues_count_offset = 0
    recent_activity = []
    prs = []

    def __init__(self):
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

    def log(self, message):
        print("Updater: " + message)

    def read_config(self):
        try:
            config = open(self.config_file, "r")
            config = config.read()
            self.config = json.loads(config)
            self.log("Got config")
            # self.log(json.dumps(self.config, indent=4))
            return True
        except:  # noqa
            return False

    def read_template(self):
        try:
            template = open(self.config["template_file"], "r")
            self.template = template.read()
            self.log("Got template file")
            self.log(self.template)
            return True
        except:  # noqa
            raise Exception("Failed reading config")

    def web_request_retry(self, url, headers=None):
        retries = 3

        if headers is None:
            if self.token:
                headers = {"Authorization": "token " + self.token}
            else:
                headers = {}

        try:
            time.sleep(0.5)
            while retries > 0:
                r = requests.get(url, headers=headers)
                if r.status_code == requests.codes.ok:
                    return r
                else:
                    self.log("Not 200 for: " + url)
                    retries = retries - 1
        except Exception as e:
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
                return [
                    {k: item[k] for k in ("html_url", "title", "updated_at", "url", "pull_request") if k in item}
                    for item in data
                ]
        elif "/gists" in url:
            # gists: only need html_url, description
            if isinstance(data, list):
                return [
                    {k: item[k] for k in ("html_url", "description") if k in item}
                    for item in data
                ]
        elif "/commits/" in url or "/git/commits/" in url:
            # commit lookups: only need html_url
            if isinstance(data, dict):
                return {k: data[k] for k in ("html_url",) if k in data}
        return data

    def web_request_retry_cached(self, url, headers=None):
        cached = self.cache.get(url)
        if cached is not None:
            self.log("Cache hit: " + url)
            return cached
        r = self.web_request_retry(url, headers)
        if r is not False:
            data = r.json()
            data = self._slim_cache_data(url, data)
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
                )
                if r.status_code == 200:
                    body = r.json()
                    if "errors" in body:
                        self.log("GraphQL errors: " + str(body["errors"]))
                        return None
                    return body.get("data")
                self.log(
                    "GraphQL HTTP " + str(r.status_code) + " (attempt " + str(attempt + 1) + ")"
                )
            except Exception as e:
                self.log("GraphQL error: " + str(e) + " (attempt " + str(attempt + 1) + ")")
            time.sleep(1)
        return None

    def get_first_commit_date_http(self, repo):
        cache_key = "first_commit:" + repo
        cached = self.perm_cache.get(cache_key)
        if cached is not None:
            self.log("Permanent cache hit for first commit: " + repo)
            return cached

        next = None

        url = (
            self.config["user_repos_url"]
            + "/"
            + repo
            + "/commits?sha=main&per_page=1&page=1"
        )
        self.log(url)
        r = self.web_request_retry(url)
        if r is not False and "link" in r.headers:
            link = r.headers["link"]
            parts = link.split("<")
            if len(parts) > 2:
                next_part = parts[2].split(">")
                next = next_part[0]

        if next != None:
            r = self.web_request_retry(next)
            if r != False:
                res = r.json()
                year = res[0]["commit"]["author"]["date"].split("-")[0]
                self.log(year)
                self.perm_cache.set(cache_key, year)
                return year

        self.log("failed")
        return ""

    def get_repos(self):
        try:
            login = self.config["user"]
            cursor = None
            all_nodes = []

            while True:
                self.log("GraphQL repos page (cursor=" + str(cursor is not None) + ")")
                data = self.fetch_graphql(REPOS_GRAPHQL, {"login": login, "cursor": cursor})
                if not data:
                    self.log("GraphQL failed, falling back to REST")
                    return self._get_repos_rest()

                user = data["user"]
                repos_data = user["repositories"]
                all_nodes.extend(repos_data["nodes"])

                if repos_data["pageInfo"]["hasNextPage"]:
                    cursor = repos_data["pageInfo"]["endCursor"]
                else:
                    break

            self.repos = []
            self.repo_languages = {}
            langs_agg = defaultdict(int)

            for node in all_nodes:
                repo = {
                    "name": node["name"],
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
                    "license": {"name": (node.get("licenseInfo") or {}).get("name")} if node.get("licenseInfo") else None,
                }
                self.repos.append(repo)

                # Store per-repo language data
                repo_langs = {}
                for edge in (node.get("languages") or {}).get("edges", []):
                    lang_name = edge["node"]["name"]
                    lang_bytes = edge["size"]
                    repo_langs[lang_name] = lang_bytes
                self.repo_languages[node["name"]] = repo_langs

                # Aggregate languages — skip forks and archived repos
                if not repo["fork"] and not repo["archived"]:
                    for lang_name, lang_bytes in repo_langs.items():
                        langs_agg[lang_name] += lang_bytes
                        self.total_lines += lang_bytes

            self.total_lines_lang = dict(langs_agg)

            self.repos.sort(key=lambda x: x["updated_at"], reverse=True)
            self.log(
                "Got repos via GraphQL: " + str(len(self.repos))
                + ", Languages: " + str(len(self.total_lines_lang))
                + ", LoC: " + str(self.total_lines)
            )
            return True
        except Exception as e:
            self.log("GraphQL get_repos error: " + str(e))
            raise Exception("Failed reading repos")

    def _get_repos_rest(self):
        """Fallback REST-based repo fetching."""
        try:
            page = 1
            self.repos = []
            while True:
                url = self.config["repos_url"] + "&page=" + str(page)
                self.log(url)
                r = self.web_request_retry(url)
                if r != False:
                    self.log("got page " + str(page))
                    res = r.json()

                    if len(res) == 0:
                        self.log("no repos, break")
                        break

                    self.repos = self.repos + res
                    page += 1
                else:
                    return False

            self.repos.sort(key=lambda x: x["updated_at"], reverse=True)
            self.log("Got repos via REST")
            return True
        except:  # noqa
            raise Exception("Failed reading repos")

    def get_repo_issues(self, repo):
        try:
            url = self.config["user_repos_url"] + "/" + repo + "/issues?state=open"
            self.log(url)
            data = self.web_request_retry_cached(url)
            if data is not None:
                return data
            else:
                self.log("No data for issues: " + repo)
        except:  # noqa
            raise Exception("Failed reading issues")

    def get_repo_pull_requests(self, repo):
        try:
            url = self.config["user_repos_url"] + "/" + repo + "/pulls?state=open"
            self.log(url)
            data = self.web_request_retry_cached(url)
            if data is not None:
                return data
            else:
                self.log("No data for pulls: " + repo)
        except:  # noqa
            raise Exception("Failed reading pull requests")

    def get_repo_languages(self, name):
        try:
            languages = self.repo_languages.get(name)

            if not languages:
                # Fallback to REST if no GraphQL data
                languages_url = self.config["user_repos_url"] + "/" + name + "/languages"
                self.log(languages_url)
                data = self.web_request_retry_cached(languages_url)
                if data is not None:
                    languages = data
                else:
                    return False

            lines = 0
            lang_percent = {}

            for count in list(languages.values()):
                lines += count

            if lines == 0:
                return False

            for lang in languages:
                lang_percent[lang] = round(round(languages[lang] / lines, 2) * 100)

            language = ""
            for lang in lang_percent:
                if lang_percent[lang] != 0:
                    badge = (
                        self.config["badges"][lang]
                        if lang in self.config["badges"]
                        else ""
                    )
                    badge = (
                        "https://img.shields.io/badge/_-"
                        + lang
                        + " -11DDDD.svg?style=for-the-badge"
                        if badge == ""
                        else badge
                    )
                    language += (
                        "<img src='" + badge + "' title='" + lang + "' height='20px'/> "
                    )

            language = language[0 : len(language) - 2]

            return language
        except:  # noqa
            raise Exception("Failed reading languages")

    def generate_repos(self):
        try:

            rows_match = re.search(
                "<repos>(.*)</repos>", self.template, flags=re.I | re.M | re.S
            )
            rows_template = rows_match.group(1).strip()

            rows = ""

            live = self.config["live"]

            live_repos = []
            old_repos = []

            self.log("generate_repos")

            fetched = 0
            for repo in self.repos:
                repo["get_first_commit_date"] = self.get_first_commit_date_http(
                    repo["name"]
                )
                self.log(repo["name"] + " -> " + repo["get_first_commit_date"])
                fetched += 1
                if fetched % 20 == 0:
                    self.perm_cache.save()

                if repo["name"] in live:
                    live_repos.append(repo)
                else:
                    old_repos.append(repo)

            self.perm_cache.save()

            live_repos = sorted(live_repos, key=itemgetter("pushed_at"))
            old_repos = sorted(
                old_repos, key=itemgetter("get_first_commit_date"), reverse=True
            )

            # Count repos per year for collapsed section headers
            year_counts = defaultdict(int)
            for repo in old_repos:
                year = repo["get_first_commit_date"]
                if year:
                    year_counts[year] += 1

            last_year_header = ""
            details_open = False

            for repo in live_repos + old_repos:

                # Skip issues/PRs fetch for repos with 0 open issues
                if repo.get("open_issues_count", 0) > 0:
                    repo_issues = self.get_repo_issues(repo["name"])
                    repo_prs = self.get_repo_pull_requests(repo["name"])
                else:
                    self.log(
                        "Skipping issues/PRs for "
                        + repo["name"]
                        + " (0 open issues)"
                    )
                    repo_issues = None
                    repo_prs = None

                if repo_issues is not None:
                    self.issues += repo_issues

                if repo_prs is not None:
                    self.prs += repo_prs

                prepend = False

                language = self.get_repo_languages(repo["name"])
                language = language if language is not False else (repo["language"] or "")
                html_url = repo["html_url"]
                name = repo["name"]
                live_url = live[repo["name"]][0] if repo["name"] in live else ""
                live_name = live[repo["name"]][1] if repo["name"] in live else ""

                if live_url != "" and live_name != "":
                    prepend = True

                license = repo["license"]["name"] if repo["license"] is not None else ""

                updated_at = (
                    repo["updated_at"] if repo["updated_at"] is not None else ""
                )

                badge = (
                    self.config["user_url"]
                    + "/"
                    + repo["name"]
                    + "/actions/workflows/main.yml/badge.svg"
                )

                row = rows_template
                row = row.replace("{language}", language)
                row = row.replace(
                    "{first_commit}", "(" + repo["get_first_commit_date"] + ")"
                )
                row = row.replace("{html_url}", html_url)
                row = row.replace("{name}", name)
                row = row.replace("{live_url}", live_url)
                row = row.replace("{live_name}", live_name)
                row = row.replace("{license}", license)
                row = row.replace("{updated_at}", updated_at.split("T")[0])
                row = row.replace("{badge}", badge)

                row = self.generate_issues(row, name)
                row = self.generate_recent_activity(row, name)
                row = self.generate_prs(row, name)

                if (
                    repo["name"] not in live
                    and last_year_header != repo["get_first_commit_date"]
                ):
                    last_year_header = repo["get_first_commit_date"]
                    count = year_counts.get(last_year_header, 0)
                    close_prev = "</tbody></table></details>" if details_open else "</tbody></table>"
                    row = (
                        close_prev
                        + "<details><summary><strong>"
                        + last_year_header
                        + " ("
                        + str(count)
                        + " projects)</strong></summary>"
                        + "<table width='100%' style='width:100%'><thead><tr><th>Project</th><th>View</th><th>Status</th></tr></thead><tbody>"
                        + row
                    )
                    details_open = True
                if prepend:
                    rows = row + "\n" + rows
                else:
                    rows = rows + "\n" + row

            # Close the final <details> if one was opened
            if details_open:
                rows += "</details>"

            self.template = re.sub(
                "<repos>(.*)</repos>", rows, self.template, flags=re.I | re.M | re.S
            )
        except Exception as e:
            self.log(str(e))
            raise Exception("Failed generating repo list")

    def generate_issues(self, template="", repo=False):
        try:
            # issues
            issues_match = re.search(
                "<ul><issues>(.*)</issues></ul>",
                self.template if repo == False else template,
                flags=re.I | re.M | re.S,
            )
            issues_template = issues_match.group(1).strip()

            issues_html = ""
            added = 0

            for issue in list(self.issues):
                if repo != False and added == 5:
                    break
                if "pull" in issue["html_url"]:
                    continue

                # print("generate_issues " + self.config["user"] + "/" + str(repo) + " in " + issue["html_url"])

                if (
                    repo == False
                    or self.config["user"] + "/" + str(repo) in issue["html_url"]
                ):
                    issue_html = issues_template
                    issue_html = issue_html.replace("{issue_url}", issue["html_url"])
                    issue_html = issue_html.replace("{issue_title}", issue["title"])
                    issue_html = issue_html.replace(
                        "{updated_at}", issue["updated_at"].split("T")[0]
                    )
                    issues_html += issue_html
                    added += 1

            if repo == False:
                self.template = self.template.replace(
                    "{issue_count}",
                    str(len(self.issues)),
                )

                self.template = re.sub(
                    "<ul><issues>(.*)</issues></ul>",
                    "<ul>" + issues_html + "</ul>",
                    self.template,
                    flags=re.I | re.M | re.S,
                )
                return True
            else:
                if added > 0:
                    issues_html = "<h4>Issues</h4><ul>" + issues_html + "</ul>"
                else:
                    issues_html = "<ul>" + issues_html + "</ul>"
                return re.sub(
                    "<ul><issues>(.*)</issues></ul>",
                    issues_html,
                    template,
                    flags=re.I | re.M | re.S,
                )
        except Exception as e:
            self.log(str(e))
            if repo:
                return template
            raise Exception("Failed generating issues")

    def generate_prs(self, template="", repo=False):
        try:
            # prs
            prs_match = re.search(
                "<ul><prs>(.*)</prs></ul>",
                self.template if repo == False else template,
                flags=re.I | re.M | re.S,
            )
            prs_template = prs_match.group(1).strip()

            prs_html = ""
            added = 0

            for pr in self.prs:
                if repo != False and added == 5:
                    break

                # print("generate_prs " + self.config["user"] + "/" + str(repo) + " in " + pr["url"])

                if repo == False or self.config["user"] + "/" + str(repo) in pr["url"]:
                    pr_html = prs_template
                    pr_html = pr_html.replace("{pr_url}", pr["html_url"])
                    pr_html = pr_html.replace("{pr_title}", pr["title"])
                    pr_html = pr_html.replace(
                        "{updated_at}", pr["updated_at"].split("T")[0]
                    )
                    prs_html += pr_html
                    added += 1

            if repo == False:
                self.template = self.template.replace("{pr_count}", str(len(self.prs)))

                self.template = re.sub(
                    "<ul><prs>(.*)</prs></ul>",
                    "<ul>" + prs_html + "</ul>",
                    self.template,
                    flags=re.I | re.M | re.S,
                )
                return True
            else:
                if added > 0:
                    prs_html = "<h4>Pull Requests</h4><ul>" + prs_html + "</ul>"
                else:
                    prs_html = "<ul>" + prs_html + "</ul>"
                return re.sub(
                    "<ul><prs>(.*)</prs></ul>",
                    prs_html,
                    template,
                    flags=re.I | re.M | re.S,
                )
        except Exception as e:
            self.log(str(e))
            if repo:
                return template
            raise Exception("Failed generating prs")

    def get_commit_html_url(self, url):
        try:
            data = self.web_request_retry_cached(url)
            if data is not None:
                return data["html_url"]
            else:
                return False
        except:  # noqa
            return url

    def generate_recent_activity(self, template="", repo=False):
        try:
            if len(self.recent_activity) == 0:
                res = self.web_request_retry(self.config["events_url"])
                if res is not False:
                    self.recent_activity = res.json()
                else:
                    return template if repo else False

            recent_match = re.search(
                "<ul><recent>(.*)</recent></ul>",
                self.template if repo == False else template,
                flags=re.I | re.M | re.S,
            )
            recent_template = recent_match.group(1).strip()

            recent_html = ""

            num = 0
            added = 0
            for recent in self.recent_activity:
                if repo != False and num == 5:
                    break

                self.log(
                    "generate_recent_activity "
                    + self.config["user"]
                    + "/"
                    + str(repo)
                    + " == "
                    + recent["repo"]["name"]
                )

                if (
                    repo == False
                    or self.config["user"] + "/" + str(repo) == recent["repo"]["name"]
                ):
                    recent_h = recent_template
                    if (
                        recent["type"] == "IssueCommentEvent"
                        and "issue" in recent["payload"]
                    ):
                        recent_h = recent_h.replace(
                            "{recent_activity_url}",
                            recent["payload"]["issue"]["html_url"],
                        )
                        recent_h = recent_h.replace(
                            "{recent_activity_title}",
                            recent["payload"]["issue"]["title"],
                        )
                        recent_html += recent_h
                        added += 1
                    elif recent["type"] == "PushEvent":
                        self.log(pprint.pformat(recent))
                        commits = recent["payload"].get("commits", [])
                        if len(commits) > 0:
                            recent_h = recent_h.replace(
                                "{recent_activity_url}",
                                self.get_commit_html_url(commits[0]["url"]),
                            )
                            recent_h = recent_h.replace(
                                "{recent_activity_title}",
                                commits[0]["message"],
                            )
                            recent_html += recent_h
                            added += 1
                    elif recent["type"] == "CreateEvent":
                        recent_h = recent_h.replace(
                            "{recent_activity_url}", recent["repo"]["url"]
                        )
                        recent_h = recent_h.replace(
                            "{recent_activity_title}", recent["repo"]["name"]
                        )
                        recent_html += recent_h
                        added += 1
                    elif (
                        recent["type"] == "PullRequestEvent"
                        and "pull_request" in recent["payload"]
                    ):
                        recent_h = recent_h.replace(
                            "{recent_activity_url}",
                            recent["payload"]["pull_request"]["html_url"],
                        )
                        recent_h = recent_h.replace(
                            "{recent_activity_title}",
                            recent["payload"]["pull_request"]["title"],
                        )
                        recent_html += recent_h
                        added += 1
                    else:
                        continue
                    num += 1

            if repo == False:
                self.template = re.sub(
                    "<ul><recent>(.*)</recent></ul>",
                    "<ul>" + recent_html + "</ul>",
                    self.template,
                    flags=re.I | re.M | re.S,
                )
                return True
            else:
                if added > 0:
                    recent_html = "<h4>Recent Activity</h4><ul>" + recent_html + "</ul>"
                else:
                    recent_html = "<ul>" + recent_html + "</ul>"
                return re.sub(
                    "<ul><recent>(.*)</recent></ul>",
                    recent_html,
                    template,
                    flags=re.I | re.M | re.S,
                )
        except Exception as e:
            self.log(str(e))
            if repo:
                return template
            raise Exception("Failed generating activity")

    def generate_gists(self):
        try:
            gists = self.web_request_retry_cached(self.config["gists_url"])
            if gists is not None:
                gists_match = re.search(
                    "<gists>(.*)</gists>", self.template, flags=re.I | re.M | re.S
                )
                gists_template = gists_match.group(1).strip()

                gists_html = ""

                for gist in gists:
                    gist_html = gists_template
                    gist_html = gist_html.replace("{gist_url}", gist["html_url"])
                    gist_html = gist_html.replace("{gist_title}", gist["description"])
                    gists_html += gist_html

                self.template = re.sub(
                    "<gists>(.*)</gists>",
                    gists_html,
                    self.template,
                    flags=re.I | re.M | re.S,
                )
            return True
        except:  # noqa
            self.log(self.template)
            raise Exception("Failed generating gists")

    def generate_orgs(self):
        try:
            # orgs
            orgs_match = re.search(
                "<orgs>(.*)</orgs>", self.template, flags=re.I | re.M | re.S
            )
            orgs_template = orgs_match.group(1).strip()

            orgs = ""

            for org in self.config["organizations"]:

                row = orgs_template
                row = row.replace("{org_url}", org[0])
                row = row.replace("{org_name}", org[1])

                orgs += row + "\n"

            self.template = re.sub(
                "<orgs>(.*)</orgs>", orgs, self.template, flags=re.I | re.M | re.S
            )
            return True
        except:  # noqa
            raise Exception("Failed generating org list")

    def favorite_langs(self):
        # langs
        langs_match = re.search(
            "<langs>(.*)</langs>", self.template, flags=re.I | re.M | re.S
        )
        langs_template = langs_match.group(1).strip()

        i = 0
        output = ""
        for lang in self.total_lines_lang:
            col = langs_template
            badge = self.config["badges"][lang] if lang in self.config["badges"] else ""
            badge = (
                "https://img.shields.io/badge/_-"
                + lang
                + " -11DDDD.svg?style=for-the-badge"
                if badge == ""
                else badge
            )
            col = col.replace(
                "{language}",
                ("<img src='" + badge + "' title='" + lang + "'  height='20px'/>"),
            )
            col = col.replace("{lines}", str(self.total_lines_lang[lang]))
            output += col + "\n"
            i += 1
            if i % 4 == 0:
                output += "</tr><tr>\n"

        self.template = re.sub(
            "<langs>(.*)</langs>", output, self.template, flags=re.I | re.M | re.S
        )

    def generate_svgs(self):
        os.makedirs("generated", exist_ok=True)

        total_stars = sum(r.get("stargazers_count", 0) for r in self.repos)
        with open("generated/stats.svg", "w") as f:
            f.write(
                svg_stats(
                    repos=len(self.repos),
                    stars=total_stars,
                    issues=len(self.issues),
                    prs=len(self.prs),
                    loc=self.total_lines,
                    lang_count=len(self.total_lines_lang),
                )
            )
        self.log("Wrote generated/stats.svg")

        with open("generated/top_repos.svg", "w") as f:
            f.write(svg_top_repos(self.repos))
        self.log("Wrote generated/top_repos.svg")

        with open("generated/timeline.svg", "w") as f:
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

            # Currently working on — most recently pushed non-profile repo
            working_on = ""
            if self.repos:
                sorted_by_push = sorted(
                    [r for r in self.repos if r["name"] != self.config["user"] and not r.get("fork", False) and not r.get("archived", False)],
                    key=lambda x: x.get("pushed_at", ""),
                    reverse=True,
                )
                if sorted_by_push:
                    cw = sorted_by_push[0]
                    cw_lang = cw.get("language") or ""
                    cw_lang_badge = ""
                    if cw_lang:
                        cw_lang_badge = " <img src='https://img.shields.io/badge/-" + cw_lang + "-informational?style=flat' alt='" + cw_lang + "'/>"
                    working_on = (
                        "<h4>Currently working on</h4>"
                        "<p><a href='" + cw["html_url"] + "'><strong>" + cw["name"] + "</strong></a>"
                        + cw_lang_badge
                        + " &mdash; last pushed " + (cw.get("pushed_at", "")[:10]) + "</p>"
                    )
            self.template = self.template.replace("{currently_working_on}", working_on)

            now = datetime.now()
            dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

            self.template = self.template.replace(
                "{github_url}", self.config["github_url"]
            )
            self.template = self.template.replace(
                "{linkedin_url}", self.config["linkedin_url"]
            )
            self.template = self.template.replace(
                "{langcount}", str(len(self.total_lines_lang) + 1)
            )
            self.template = self.template.replace("{last_updated}", dt_string)

            self.log(self.template)

            f = open("README.md", "w")
            f.write(self.template)
            f.close()
            return True

        except:  # noqa
            raise Exception("Failed generating readme")


ReadmeUpdater()
