"""A repo's first commit: the one date that places every repo on the profile.

GitHub's created_at is when a repo was pushed to GitHub, not when the project began,
so years, sorting and the timeline all use the author date of the oldest commit on the
default branch.
"""

import re

CACHE_PREFIX = "first_commit_date:"


def fetch_first_commit_date(request, repos_url, repo):
    """Return the ISO author date of the oldest commit on the default branch, or "".

    request(url) returns a requests.Response or False. With per_page=1 the "last" page
    of the commit list holds the first commit; a repo with one commit has no "last" link.
    """
    url = repos_url + "/" + repo["name"] + "/commits?sha=" + repo.get("default_branch", "main") + "&per_page=1"
    response = request(url)
    if response is False:
        return ""
    last = re.search(r'<([^>]+)>;\s*rel="last"', response.headers.get("link", ""))
    if last:
        response = request(last.group(1))
        if response is False:
            return ""
    commits = response.json()
    if not commits:
        return ""
    return commits[-1]["commit"]["author"]["date"]


def first_commit_year(repo):
    """The year shown and grouped on for a repo, from its first commit."""
    return (repo.get("first_commit_date") or "")[:4]


def by_first_commit(repos):
    """Newest first commit first."""
    return sorted(repos, key=lambda r: r.get("first_commit_date") or "", reverse=True)
