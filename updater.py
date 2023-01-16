import json
import requests
import re

repos_url = 'https://api.github.com/users/dmzoneill/repos'
url_url = 'https://api.github.com/users/dmzoneill'

r = requests.get(repos_url)

if r.status_code == requests.codes.ok:
    repos = r.json()

    config = open("config.json", "r")
    config = config.read()
    config = json.loads(config)
    live = config['live']

    template = open("template.md", "r")
    template = template.read()

    # repos
    rows_match = re.search('<repos>(.*)</repos>',
                           template, flags=re.I | re.M | re.S)
    rows_template = rows_match.group(1).strip()

    rows = ""

    repos.sort(key=lambda x: x["updated_at"], reverse=True)

    for repo in repos:

        language = repo['language'] if repo['language'] is not None else ""
        html_url = repo['html_url']
        name = repo['name']
        live_url = live[repo['name']][0] if repo['name'] in live else ""
        live_name = live[repo['name']][1] if repo['name'] in live else ""
        license = repo['license']['name'] if repo['license'] is not None else ""
        updated_at = repo['updated_at'] if repo['updated_at'] is not None else ""
        open_issues_count = str(repo['open_issues_count'])

        row = rows_template
        row = row.replace("{language}", language)
        row = row.replace("{html_url}", html_url)
        row = row.replace("{name}", name)
        row = row.replace("{live_url}", live_url)
        row = row.replace("{live_name}", live_name)
        row = row.replace("{license}", license)
        row = row.replace("{updated_at}", updated_at)
        row = row.replace("{open_issues_count}", open_issues_count)

        rows += row + "\n"

    # orgs
    orgs_match = re.search('<orgs>(.*)</orgs>', template,
                           flags=re.I | re.M | re.S)
    orgs_template = orgs_match.group(1).strip()

    orgs = ""

    for org in config['organizations']:

        row = orgs_template
        row = row.replace("{org_url}", org[0])
        row = row.replace("{org_name}", org[1])

        orgs += row + "\n"

    template = template.replace("{github_url}", config['github_url'])
    template = template.replace("{linkedin_url}", config['linkedin_url'])
    template = re.sub('<orgs>(.*)</orgs>', orgs,
                      template, flags=re.I | re.M | re.S)
    template = re.sub('<repos>(.*)</repos>', rows,
                      template, flags=re.I | re.M | re.S)
    print(template)

    f = open("README.md", "w")
    f.write(template)
    f.close()