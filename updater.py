import json
import os
import re
from pprint import pprint

import requests


class ReadmeUpdater:

    repos_url = "https://api.github.com/users/dmzoneill/repos?per_page=100"
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

    def __init__(self):
        self.read_config()
        self.read_template()
        self.prep_cache()
        self.get_repos()
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

    def prep_cache(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def get_cached_file(self, name):
        try:
            cache_file = open(self.cache_dir + "/" + name, "r")
            cache_file = cache_file.read()
            print("Got cache file: " + name)
            return cache_file
        except:  # noqa
            return False

    def cache_file(self, name, content):
        try:
            # self.prep_cache()
            # f = open(self.cache_dir + "/" + name, "w")
            # f.write(content)
            # f.close()
            print("Write cache file: " + name)
        except:  # noqa
            raise Exception("Unable to cache: " + name)

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
            self.cache_file("repos", json.dumps(self.repos))
            print("Got repos")
            return True
        except:  # noqa
            raise Exception("Failed reading repos")

    def get_repo_languages(self, name):
        try:
            # https://api.github.com/repos/dmzoneill/aa-dev-prod-watcher/languages
            languages_url = (
                "https://api.github.com/repos/dmzoneill/" + name + "/languages"
            )
            cache = self.get_cached_file(name)
            languages = None

            if cache is False:
                headers = {"Authorization": "token " + self.token}
                res = requests.get(languages_url, headers=headers)
                if res.status_code == requests.codes.ok:
                    languages = res.json()
            else:
                languages = json.loads(cache)

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

            if cache is False:
                self.cache_file(name, json.dumps(languages))
                pprint(json.dumps(languages))

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

                language = self.get_repo_languages(repo["name"])
                language = language if language is not False else repo["language"]

                html_url = repo["html_url"]
                name = repo["name"]
                live_url = live[repo["name"]][0] if repo["name"] in live else ""
                live_name = live[repo["name"]][1] if repo["name"] in live else ""
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
                row = row.replace("{html_url}", html_url)
                row = row.replace("{name}", name)
                row = row.replace("{live_url}", live_url)
                row = row.replace("{live_name}", live_name)
                row = row.replace("{license}", license)
                row = row.replace("{updated_at}", updated_at.split("T")[0])
                row = row.replace("{badge}", badge)

                rows += row + "\n"
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
                "<img src='" + badge + "' title='" + lang + "'  height='20px'/>",
            )
            col = col.replace("{lines}", str(self.total_lines_lang[lang]))
            output += col + "\n"
            i += 1
            if i % 4 == 0:
                output += "</tr><tr>\n"

        self.template = re.sub(
            "<langs>(.*)</langs>", output, self.template, flags=re.I | re.M | re.S
        )

    def generate_readme(self):
        try:
            self.generate_orgs()
            self.generate_repos()
            self.favourite_langs()
            self.template = self.template.replace(
                "{github_url}", self.config["github_url"]
            )
            self.template = self.template.replace(
                "{linkedin_url}", self.config["linkedin_url"]
            )
            self.template = self.template.replace(
                "{langcount}", str(len(self.total_lines_lang) + 1)
            )

            print(self.template)

            f = open("README.md", "w")
            f.write(self.template)
            f.close()
            return True

        except:  # noqa
            raise Exception("Failed generating readme")


ReadmeUpdater()
