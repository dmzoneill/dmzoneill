import json
import os
import re
from datetime import datetime
from pprint import pprint

import requests


class ReadmeUpdater:

    repos_url = "https://api.github.com/users/dmzoneill/repos?per_page=100&type=owner&sort=pushed"
    url_url = "https://api.github.com/users/dmzoneill"
    cache_dir = "./cache"
    config_file = "config.json"
    template_file = "template.md"
    config = None
    template = None
    repos = None
    token = os.getenv("ghtoken", default=None)
    total_lines = 0
    total_lines_lang = {}  # type: ignore
    issues = []
    issues_count_offset = 0
    prs = []

    def __init__(self):
        self.read_config()
        self.read_template()
        if self.get_repos() is False:
            print("Rate limited")
            return
        self.generate_readme()

    def read_config(self):
        try:
            config = open(self.config_file, "r")
            config = config.read()
            self.config = json.loads(config)
            print("Got config")
            return True
        except:  # noqa
            return False

    def read_template(self):
        try:
            template = open(self.template_file, "r")
            self.template = template.read()
            print("Got template file")
            return True
        except:  # noqa
            raise Exception("Failed reading config")

    def get_first_commit_date(self, repo):
        try:
            query = """
            {
                repository(owner: "#owner#", name: "#repo#") {
                    refs(refPrefix: "refs/heads/", orderBy: {
                        direction: DESC,
                        field: TAG_COMMIT_DATE
                    }, first: 1) {
                    edges {
                        node {
                        ... on Ref {
                            name
                            target {
                            ... on Commit {
                                history(first: 2) {
                                edges {
                                    node {
                                    ... on Commit {
                                        committedDate
                                    }
                                    }
                                }
                                }
                            }
                            }
                        }
                        }
                    }
                    }
                }
            }
            """

            query = query.replace("#owner#", "dmzoneill")
            query = query.replace("#repo#", repo)

            headers = {"Authorization": "token " + self.token}
            request = requests.post(
                "https://api.github.com/graphql", json={"query": query}, headers=headers
            )
            if request.status_code == 200:
                data = request.json()
                edge = data["data"]["repository"]["refs"]["edges"][0]
                edge = edge["node"]["target"]["history"]["edges"][1]
                return "(" + edge["node"]["committedDate"].split("-")[0] + ")"
            else:
                return ""
        except:  # noqa
            return ""

    def get_repos(self):
        try:
            headers = {"Authorization": "token " + self.token}
            page = 1
            while True:
                r = requests.get(self.repos_url + "&page=" + str(page), headers=headers)
                if r.status_code == requests.codes.ok:
                    print("got page " + str(page))
                    res = r.json()
                    if len(res) == 0:
                        print("no repos, break")
                        break

                    if self.repos is not None:
                        self.repos = self.repos + res
                    else:
                        self.repos = res
                    page += 1
                else:
                    return False

            self.repos.sort(key=lambda x: x["updated_at"], reverse=True)
            print("Got repos")
            return True
        except:  # noqa
            raise Exception("Failed reading repos")

    def get_repo_issues(self, repo):
        try:
            url = (
                "https://api.github.com/repos/dmzoneill/" + repo + "/issues?state=open"
            )
            headers = {"Authorization": "token " + self.token}
            res = requests.get(url, headers=headers)
            if res.status_code == requests.codes.ok:
                return res.json()
        except:  # noqa
            raise Exception("Failed reading issues")

    def get_repo_pull_requests(self, repo):
        try:
            url = "https://api.github.com/repos/dmzoneill/" + repo + "/pulls?state=open"
            headers = {"Authorization": "token " + self.token}
            res = requests.get(url, headers=headers)
            if res.status_code == requests.codes.ok:
                return res.json()
        except:  # noqa
            raise Exception("Failed reading pull requests")

    def get_repo_languages(self, name):
        try:
            languages_url = (
                "https://api.github.com/repos/dmzoneill/" + name + "/languages"
            )
            languages = None

            headers = {"Authorization": "token " + self.token}
            res = requests.get(languages_url, headers=headers)
            if res.status_code == requests.codes.ok:
                languages = res.json()

            lines = 0
            lang_percent = {}

            if languages is None:
                return False

            for count in list(languages.values()):
                lines += count
                self.total_lines += count

            for lang in languages:
                if lang not in self.total_lines_lang:
                    self.total_lines_lang[lang] = 0
                self.total_lines_lang[lang] += languages[lang]
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
                        "<img src='"
                        + badge
                        + "' title='"
                        + badge
                        + "' height='20px'/> "
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

            for repo in self.repos:

                repo_issues = self.get_repo_issues(repo["name"])
                repo_prs = self.get_repo_pull_requests(repo["name"])

                self.issues += repo_issues
                self.prs += repo_prs

                prepend = False

                language = self.get_repo_languages(repo["name"])
                language = language if language is not False else repo["language"]
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
                    "https://github.com/dmzoneill/"
                    + repo["name"]
                    + "/actions/workflows/main.yml/badge.svg"
                )

                row = rows_template
                row = row.replace("{language}", language)
                row = row.replace(
                    "{first_commit}", self.get_first_commit_date(repo["name"])
                )
                row = row.replace("{html_url}", html_url)
                row = row.replace("{name}", name)
                row = row.replace("{live_url}", live_url)
                row = row.replace("{live_name}", live_name)
                row = row.replace("{license}", license)
                row = row.replace("{updated_at}", updated_at.split("T")[0])
                row = row.replace("{badge}", badge)

                ## issues
                issues_match = re.search(
                    "<ul><issues>(.*)</issues></ul>", row, flags=re.I | re.M | re.S
                )
                issues_template = issues_match.group(1).strip()

                issues_html = ""

                if len(repo_issues) > 0:
                    issues_html = "<h4>Issues</h4><ul>"

                for issue in repo_issues:
                    if "pull" in issue["html_url"]:
                        continue

                    issue_html = issues_template
                    issue_html = issue_html.replace("{issue_url}", issue["html_url"])
                    issue_html = issue_html.replace("{issue_title}", issue["title"])
                    issues_html += issue_html

                if len(repo_issues) > 0:
                    issues_html += "</ul>"

                row = re.sub(
                    "<ul><issues>(.*)</issues></ul>",
                    issues_html,
                    row,
                    flags=re.I | re.M | re.S,
                )

                ## prs
                prs_match = re.search(
                    "<ul><prs>(.*)</prs></ul>", row, flags=re.I | re.M | re.S
                )
                prs_template = prs_match.group(1).strip()

                prs_html = ""

                if len(repo_issues) > 0:
                    prs_html = "<h4>Pull requests</h4><ul>"

                for pr in repo_prs:
                    pr_html = prs_template
                    pr_html = issue_html.replace("{issue_url}", pr["html_url"])
                    pr_html = issue_html.replace("{issue_title}", pr["title"])
                    prs_html += pr_html

                if len(repo_prs) > 0:
                    prs_html += "</ul>"

                row = re.sub(
                    "<ul><prs>(.*)</prs></ul>", prs_html, row, flags=re.I | re.M | re.S
                )

                if prepend:
                    rows = row + "\n" + rows
                else:
                    rows = rows + "\n" + row
            self.template = re.sub(
                "<repos>(.*)</repos>", rows, self.template, flags=re.I | re.M | re.S
            )
        except:  # noqa
            raise Exception("Failed generating repo list")

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

    def favourite_langs(self):
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

    def generate_prs(self):
        ## prs
        prs_match = re.search(
            "<prs>(.*)</prs>", self.template, flags=re.I | re.M | re.S
        )
        prs_template = prs_match.group(1).strip()

        prs_html = ""

        for pr in self.prs:
            pr_html = prs_template
            pr_html = pr_html.replace("{pr_url}", pr["html_url"])
            pr_html = pr_html.replace("{pr_title}", pr["title"])
            prs_html += pr_html

        self.template = re.sub(
            "<prs>(.*)</prs>", prs_html, self.template, flags=re.I | re.M | re.S
        )

        self.template = self.template.replace("{pr_count}", str(len(self.prs)))

    def generate_issues(self):
        ## issues
        issues_match = re.search(
            "<issues>(.*)</issues>", self.template, flags=re.I | re.M | re.S
        )
        issues_template = issues_match.group(1).strip()

        issues_html = ""

        for issue in list(self.issues):
            if "pull" in issue["html_url"]:
                self.issues_count_offset += 1
                continue
            issue_html = issues_template
            issue_html = issue_html.replace("{issue_url}", issue["html_url"])
            issue_html = issue_html.replace("{issue_title}", issue["title"])
            issues_html += issue_html

        self.template = re.sub(
            "<issues>(.*)</issues>",
            issues_html,
            self.template,
            flags=re.I | re.M | re.S,
        )

        self.template = self.template.replace(
            "{issue_count}", str(len(self.issues) - self.issues_count_offset)
        )

    def generate_readme(self):
        try:
            self.generate_orgs()
            self.generate_repos()
            self.favourite_langs()
            self.generate_prs()
            self.generate_issues()

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

            print(self.template)

            f = open("README.md", "w")
            f.write(self.template)
            f.close()
            return True

        except:  # noqa
            raise Exception("Failed generating readme")


ReadmeUpdater()
