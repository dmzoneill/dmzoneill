import base64
import os
import re
from datetime import datetime
from pathlib import Path

import requests

# GitHub API token (keep it secure)
GITHUB_API_TOKEN = os.getenv("PROFILE_HOOK")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_RUN_ID = os.getenv("GITHUB_RUN_ID")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPOSITORY").split("/")[1]

# WordPress API details
WORDPRESS_URL = os.getenv("WORDPRESS_URL")
WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME")
WORDPRESS_PASSWORD = os.getenv("WORDPRESS_PASSWORD")
WORDPRESS_APPLICATION = os.getenv("WORDPRESS_APPLICATION")

print(GITHUB_USER)
print(GITHUB_RUN_ID)
print(GITHUB_REPO_NAME)

system_prompt = """
Please generate a blog post based on the provided release diff.
The content should be formatted in **HTML for WordPress**, not markdown.

Make sure the **Title** is always placed at the top and follows this format:
<h1>Title: some title</h1>. This should be the very first line of the blog post.

Then, proceed to generate the rest of the content in a personal and relatable style,
using **HTML tags** for formatting (like <p>, <ul>, <li>, etc.) and avoiding markdown
formatting (like **bold**, *italic*, etc.). Keep the tone friendly,
simple, and easy to read, with clear structure. Do not use markdown syntax.

1. **Summarize the Diff**
    Start with a simple summary of what’s changed—whether it's files, lines, or small tweaks.
    It could be a mix of bug fixes, refactoring, or small improvements like better formatting
    or clearer comments. Even small changes matter!

2. **How Does This Change the Project?**
    Reflect on what the update means in a real-world sense. Was there a noticeable improvement
    in code quality, or did we fix something that was causing frustration? Talk about the practical
    effects of the changes—did it help clean things up, make the project easier to use,
    or smooth out an annoying bug?

3. **Bug Fixes, Refactoring, and Feature Enhancements**
    If the changes involved bug fixes, explain what got fixed and why it matters.
    If there was refactoring, keep it casual but explain how the code is now cleaner
    or easier to maintain. If there were no new features, mention it without any over-the-top
    language—just a simple acknowledgment that this is a small but meaningful update.

4. **What About Dependencies or Configurations?**
    If you made any changes to dependencies, testing setups, or configurations, mention them briefly.
    If nothing in this area was changed, feel free to say so. We want the post to be clear
    and not overhype anything.

5. **Release Info and Links**
    Give a quick heads-up about the version number and any relevant links.
    If it’s a minor release, be honest about it—don’t exaggerate the importance of the update,
    but let people know where they can find more details.

**Post Format:**

- **Start with a Title**
    Ensure the **Title** is the first line and follows the format Title: some title.

- **HTML Format for WordPress**
    Make sure the content is ready to go for WordPress. Skip any HTML comments (no <!-- comment -->),
    and make sure the links are valid, including for images or GitHub references.
    If there’s an image in the README, include that in the post if it fits!

- **Keep It Real**
    The tone should feel like you’re sharing the update with a friend—nothing too formal or
    too grandiose. If the changes are small (like updating a TODO file), let people know that
    the update is more about cleaning things up than adding huge new features.

- **GitHub Page Reference**
    Don’t forget to include the GitHub user page https://github.com/dmzoneill/ when needed.

- **Media*
    At the end of the post it's important to include the following 2 items.
    Below is an example of the 2 items, "image_idea" and "youtube_topics".
    Replace the values as necessary with the instructions provided.
    Dont add any html formatting to these items.
    Example:
        image_idea: A clear idea of a visual related to the topic
        youtube_topics: topic for first video, topic for second video

The key is to make the post feel like a casual, friendly update, rather than a corporate announcement.
Let people know what changed, why it matters, and how it will affect them—but keep it laid-back and easy to read.
"""


class OpenAIProvider:

    def __init__(self) -> None:
        self.api_key: str = os.getenv("AI_API_KEY")
        self.endpoint: str = "https://api.openai.com/v1/chat/completions"
        self.model: str = os.getenv("AI_MODEL")

    def improve_text(self, prompt: str, text: str) -> str:
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.4,
        }

        try:
            # Make the API request
            response: requests.Response = requests.post(
                self.endpoint, json=body, headers=headers, timeout=120
            )

            # Check for successful response
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()

            # If the request fails, raise an error with the response details
            raise Exception(
                f"OpenAI API call failed: {response.status_code} - {response.text}"
            )
        except requests.exceptions.RequestException as e:
            # Catch any request-related exceptions (e.g., network issues,
            # timeouts)
            raise Exception(f"Request failed: {str(e)}")


def search_image_url_unsplash(query: str, api_key: str) -> str:
    """
    Search for an image URL on Unsplash based on the query.

    :param query: Search query for the image.
    :param api_key: Unsplash API key.
    :return: URL of the image or None if not found.
    """
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {api_key}"}
    params = {"query": query, "per_page": 1, "orientation": "landscape"}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            return data["results"][0]["urls"]["regular"]
    return None


def upload_image_to_wordpress(image_url: str, image_name: str) -> str:
    """
    Upload an image to WordPress and return its URL.

    :param image_url: URL of the image to upload.
    :param image_name: Name of the image file.
    :return: URL of the uploaded image or None if upload fails.
    """
    try:
        auth = f'Basic {base64.b64encode(f"{WORDPRESS_USERNAME}:{WORDPRESS_APPLICATION}".encode()).decode()}'
        img_data = requests.get(image_url, timeout=30).content
        media_url = f"{WORDPRESS_URL}media"
        headers = {
            "Content-Disposition": f"attachment; filename={image_name}",
            "Content-Type": "image/jpeg",
            "Authorization": auth,
        }
        response = requests.post(media_url, headers=headers, data=img_data, timeout=30)
        if response.status_code == 201:
            return response.json().get("source_url")
        print(f"WordPress upload failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Image upload failed: {e}")
    return None


def search_youtube_video(topic: str, api_key: str) -> str:
    """
    Search for a YouTube video based on the topic.

    :param topic: Search query for the video.
    :param api_key: YouTube API key.
    :return: Embed URL of the video or None if not found.
    """
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": topic,
        "type": "video",
        "maxResults": 1,
        "videoEmbeddable": "true",
        "key": api_key,
    }
    response = requests.get(url, params=params, timeout=30)
    if response.status_code == 200:
        data = response.json()
        if data["items"]:
            return f"https://www.youtube.com/embed/{data['items'][0]['id']['videoId']}"
    return None


def append_enrichment_to_post(content: str, video_url: str) -> str:
    """
    Append YouTube video enrichment to the blog post content.

    :param content: Original blog post content.
    :param video_url: YouTube video URL to embed.
    :return: Enriched blog post content.
    """
    enrichment = ""
    if video_url:
        enrichment = "\n\n<hr><h2>📚 Further Learning</h2>\n"
        enrichment += f'<p>🎥 Watch this video for more:</p>\n<iframe width="710" height="415" src="{video_url}" frameborder="0" allowfullscreen></iframe>\n'
    return content + enrichment


def get_release_url(job_name="cicd / Pypi publish", pattern=None):
    """
    Function to fetch job logs from a GitHub Actions pipeline run and search for a specific pattern.

    :param run_id: GitHub Actions run ID
    :param job_name: Name of the job to search for logs (e.g., "cicd / Pypi publish")
    :param pattern: Regular expression pattern to search for in the logs
    :return: First match of the pattern or None if not found
    """
    # GitHub API URL for the actions jobs
    workflow_runs_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/actions/runs/{GITHUB_RUN_ID}/jobs"

    headers = {"Authorization": f"token {GITHUB_API_TOKEN}"}

    # Get all jobs for the given pipeline run
    response = requests.get(workflow_runs_url, headers=headers, timeout=30)

    if response.status_code == 200:
        jobs = response.json().get("jobs", [])

        # Find the specific job that corresponds to the provided job_name
        for job in jobs:
            if job["name"].lower() == job_name.lower():

                # Get the job ID and use it to fetch the logs
                job_id = job["id"]
                log_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/actions/jobs/{job_id}/logs"

                # Fetch logs for the specific job using its job_id
                log_response = requests.get(log_url, headers=headers, timeout=30)

                if log_response.status_code == 200:
                    logs = log_response.text  # Logs are plain text, not JSON

                    # If no pattern is provided, return logs as is
                    if not pattern:
                        return logs

                    # Search for the pattern in the log output
                    match = re.search(pattern, logs)

                    if match:
                        return match.group(1)
                    print(f"Pattern not found in the logs for job {job_name}.")
                    return None

                print(
                    f"Failed to fetch logs for job {job_name}. Status Code: {log_response.status_code}"
                )
                return None
    print(f"Failed to fetch workflow jobs. Status Code: {response.status_code}")
    return None


# Fetch the programming languages used in the GitHub repo
def get_github_languages():
    languages_url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/languages"
    )
    languages_response = requests.get(
        languages_url,
        headers={"Authorization": f"token {GITHUB_API_TOKEN}"},
        timeout=30,
    )

    if languages_response.status_code == 200:
        languages_data = languages_response.json()
        # Return a list of programming languages used in the repository
        return list(languages_data.keys())

    print(f"Failed to fetch programming languages for {GITHUB_REPO_NAME}.")
    return []


# Example function to get the release links
# Example function to get the release links
def get_release_links():
    release_links = {}

    # Get GitHub Release Link and Assets
    release_data = get_github_release()
    if release_data:
        release_links["github_release"] = release_data.get(
            "github_release", "Not available"
        )
        release_links["assets"] = release_data.get("assets", {})

    # Fetch PyPI URL from the logs
    pypi_url = get_release_url(
        job_name="cicd / Pypi publish", pattern=r"(https://pypi\.org/project/[^/]+/\S+)"
    )
    if pypi_url:
        release_links["pypi"] = pypi_url
    else:
        print("Failed to retrieve PyPI URL.")

    # Fetch Docker Hub or GCR URL from the logs (using a pattern for pushing
    # manifest)
    docker_url = get_release_url(
        job_name="cicd / Docker publish", pattern=r"pushing manifest for s*(docker.*)"
    )
    if docker_url:
        release_links["docker_hub"] = docker_url
    else:
        print("Failed to retrieve Docker Push URL.")

    # Fetch Docker Hub or GCR URL from the logs (using a pattern for pushing
    # manifest)
    docker_url = get_release_url(
        job_name="cicd / Docker publish", pattern=r"pushing manifest for s*(ghcr.*)"
    )
    if docker_url:
        release_links["ghcr_hub"] = docker_url
    else:
        print("Failed to retrieve GHCR Push URL.")

    return release_links


# Function to remove enclosing code block markers (like ```html, ```)
def clean_html_code_block(content):
    content = re.sub(
        r"^```.*?$", "", content, flags=re.MULTILINE
    )  # Remove start of code block
    content = re.sub(r"```$", "", content)  # Remove end of code block
    return content


# Function to strip HTML tags from a string (for title and excerpt)
def strip_html_tags(text):
    return re.sub(r"<[^>]*>", "", text)


# Fetch GitHub Release Link and associated assets (such as RPM, DEB)
def get_github_release():
    release_url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/releases/latest"
    )
    release_response = requests.get(
        release_url, headers={"Authorization": f"token {GITHUB_API_TOKEN}"}, timeout=30
    )

    if release_response.status_code == 200:
        release_data = release_response.json()

        # Getting the GitHub release URL
        github_release_url = release_data.get(
            "html_url", "Not available"
        )  # Release URL

        # Find assets (deb, rpm, etc.) from the release
        assets = release_data.get("assets", [])
        release_links = {"github_release": github_release_url, "assets": {}}

        # Look through assets and find deb, rpm files
        for asset in assets:
            if ".deb" in asset["name"]:
                release_links["assets"]["deb"] = asset["browser_download_url"]
            if ".rpm" in asset["name"]:
                release_links["assets"]["rpm"] = asset["browser_download_url"]

        return release_links
    print(f"Failed to fetch release details for {GITHUB_REPO_NAME}.")
    return {}


# Fetch existing tags from WordPress or create them if they don't exist
def get_or_create_tags(tags):
    tag_ids = []
    tags_url = f"{WORDPRESS_URL}tags"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f'Basic {base64.b64encode(f"{WORDPRESS_USERNAME}:{WORDPRESS_APPLICATION}".encode()).decode()}',
    }

    response = requests.get(
        tags_url, headers=headers, params={"page": 1, "per_page": 100}, timeout=30
    )
    if response.status_code == 200:
        existing_tags = response.json()
        existing_tag_names = {tag["name"].lower(): tag["id"] for tag in existing_tags}

        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower in existing_tag_names:
                tag_ids.append(existing_tag_names[tag_lower])
            else:
                create_tag_url = f"{WORDPRESS_URL}tags"
                create_tag_data = {"name": tag}
                create_response = requests.post(
                    create_tag_url, json=create_tag_data, headers=headers, timeout=30
                )
                if create_response.status_code == 201:
                    new_tag = create_response.json()
                    tag_ids.append(new_tag["id"])
                else:
                    print(f"Failed to create tag '{tag}'.")
    else:
        print(f"Failed to fetch tags. Status code: {response.status_code}")

    return tag_ids


def get_category_id(languages, categories):
    category_id = []

    # Loop through each category and check if any category name matches the
    # programming languages
    for category in categories:
        for language in languages:
            if language.lower() == category["name"].lower():
                category_id = category["id"]
                break

    return category_id


# Create WordPress post with the given title, content, and tags
def create_wordpress_post(
    title, content, publish_date, excerpt, featured_image_url=None
):
    url = f"{WORDPRESS_URL}posts"
    creds = f"{WORDPRESS_USERNAME}:{WORDPRESS_APPLICATION}".encode()
    creds = base64.b64encode(creds).decode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {creds}"}

    languages = get_github_languages()
    if not languages:
        print(f"No programming languages found for {GITHUB_REPO_NAME}.")
        return None

    tag_ids = get_or_create_tags(languages)
    categories_url = f"{WORDPRESS_URL}categories"
    response = requests.get(
        categories_url, headers=headers, params={"page": 1, "per_page": 100}, timeout=30
    )
    category_id = ""
    if response.status_code == 200:
        categories = response.json()
        category_id = get_category_id(languages, categories)

        if not category_id:
            print(
                f"No matching categories found for {GITHUB_REPO_NAME}. Using default category."
            )

    clean_content = clean_html_code_block(content)
    title = strip_html_tags(clean_html_code_block(title))
    excerpt = strip_html_tags(clean_html_code_block(excerpt))

    post_data = {
        "title": title,
        "content": clean_content,
        "status": "publish",
        "date": publish_date,
        "excerpt": excerpt,
        "slug": title.replace(" ", "-").lower(),
        "tags": tag_ids,
        "categories": category_id,
    }

    # If a featured image URL is provided, upload it and set it as the
    # featured image
    if featured_image_url:
        print(f"Featured image url: {featured_image_url}")
        try:
            img_data = requests.get(featured_image_url, timeout=30).content
            media_url = f"{WORDPRESS_URL}media"
            media_headers = {
                "Content-Disposition": f"attachment; filename={title}.jpg",
                "Content-Type": "image/jpeg",
                "Authorization": f"Basic {creds}",
            }
            media_response = requests.post(
                media_url, headers=media_headers, data=img_data, timeout=30
            )
            if media_response.status_code == 201:
                print(f"Uploaded featured image: {featured_image_url}")
                media_id = media_response.json().get("id")
                if media_id:
                    print("added featured image to post")
                    post_data["featured_media"] = media_id
            else:
                print(
                    f"Failed to upload featured image: {media_response.status_code} - {media_response.text}"
                )
        except Exception as e:
            print(f"Error uploading featured image: {e}")

    try:
        response = requests.post(url, json=post_data, headers=headers, timeout=30)
        if response.status_code == 201:
            print(f"Post created successfully! URL: {response.json()['link']}")
            return response.json()
        print(f"Failed to create post. Status Code: {response.status_code}")
        return None

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {str(e)}")
        return None


# Function to generate the blog post prompt for OpenAI
def generate_blog_post_prompt(release_links, diff, publish_date):
    prompt = f"Generate a blog post with the following release {publish_date}"
    prompt += " links and provide ana analysis of the changes from this diff:\n"

    prompt += "\n\n"
    prompt += diff
    prompt += "\n\n"

    prompt += f"\n- GitHub Release: {release_links['github_release']}\n"

    # Loop through assets if available
    if "deb" in release_links["assets"]:
        prompt += f"- Debian Package: {release_links['assets']['deb']}\n"
    if "rpm" in release_links["assets"]:
        prompt += f"- RPM Package: {release_links['assets']['rpm']}\n"

    # Additional release links
    if "chrome_extension" in release_links:
        prompt += f"- Chrome Extension Release: {release_links['chrome_extension']}\n"
    if "pypi" in release_links:
        prompt += f"- PyPI Release: {release_links['pypi']}\n"
    if "docker_hub" in release_links:
        prompt += f"- Docker Hub Release: {release_links['docker_hub']}\n"
    if "ghcr_hub" in release_links:
        prompt += f"- GHCR Release: {release_links['ghcr_hub']}\n"

    return prompt + "\n\nPlease include a title for the post."


def get_commit_diff(sha):
    """
    Fetch the commit diff for a given commit SHA in a repository, including file names in the diff output.

    :param sha: The commit SHA
    :param repo_name: The repository name (e.g., 'username/repository')
    :return: The commit diff as a string, or None if not found
    """
    # GitHub API URL for the commit details (this returns diff information in
    # the files section)
    commit_url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/commits/{sha}"
    )

    headers = {"Authorization": f"token {GITHUB_API_TOKEN}"}

    # Fetch the commit details
    response = requests.get(commit_url, headers=headers, timeout=30)

    if response.status_code == 200:
        commit_data = response.json()

        # Initialize list to store diffs
        diffs = []

        # Iterate over the files changed in this commit and collect diffs
        for file in commit_data.get("files", []):
            # GitHub provides a diff for each file change
            if "patch" in file:
                # Format the diff to include file names, as in a typical
                # unified diff
                diff = f"diff --git a/{file['filename']} b/{file['filename']}\n"
                diff += file["patch"]  # This contains the diff for that file
                diffs.append(diff)

        if diffs:
            return "\n".join(diffs)  # Combine all diffs for the commit

        print("No diff data available in the commit.")
        return None
    print(
        f"Failed to fetch commit details for SHA {sha}. Status Code: {response.status_code}"
    )
    return None


def generate_description_with_media(prompt: str):
    ai_provider = OpenAIProvider()

    response = ai_provider.improve_text(system_prompt, prompt)

    # Use regex to extract image_idea and youtube_topics
    image_match = re.search(r"image_idea:\s*(.*?)$", response, re.MULTILINE)
    youtube_match = re.search(r"youtube_topics:\s*(.*?)$", response, re.MULTILINE)

    image_idea = None
    youtube_topics = []

    print("=== generate_description_with_media ===")
    print(response)

    # Extract image_idea if match is found
    if image_match:
        image_idea = image_match.group(1).strip()
    else:
        print("No image_idea found in the response.")

    # Extract youtube_topics if match is found
    if youtube_match:
        youtube_topics_raw = youtube_match.group(1).strip()
        youtube_topics = [topic.strip() for topic in youtube_topics_raw.split(",")]
    else:
        print("No youtube_topics found in the response.")

    # Remove the media-related lines from the response to get the content
    if image_match:
        response = response[: image_match.start()].strip()

    # Extract the title from the response
    title_match = re.search(r"Title:\s*(.*)", response)
    if title_match:
        title = title_match.group(1).strip()
        content = re.sub(r"Title:\s*.*\n", "", response).strip()
        return title, content, image_idea, youtube_topics

    return None, response, image_idea, youtube_topics


def is_substantial_change(
    diff: str, commit_message: str, override_keyword="Blog = true"
) -> bool:
    # Force include if override keyword is in commit message
    if override_keyword.lower() in commit_message.lower():
        return True

    if not diff or not commit_message:
        return False

    # Count added and removed lines
    added_lines = sum(
        1
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed_lines = sum(
        1
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    total_changes = added_lines + removed_lines

    # Extract changed files
    changed_files = re.findall(r"^diff --git a/(.+?) b/\1", diff, re.MULTILINE)

    if not changed_files:
        return False

    # Skip if all files are dotfiles or in .github/** or similar
    all_hidden = all(
        Path(file).parts[0].startswith(".") or "/." in file for file in changed_files
    )
    if all_hidden:
        return False

    # CommitLint type detection
    commit_type_match = re.match(
        r"^(feat|fix|perf|docs|chore|style|refactor|test|ci|build)(\(.+\))?:",
        commit_message.strip(),
    )
    commit_type = commit_type_match.group(1) if commit_type_match else None

    # If it's a code-impacting type, consider it substantial if any changes were made
    if commit_type in {"feat", "fix", "perf"}:
        return True

    # For others, check if there's at least one non-trivial change
    if total_changes >= 25:
        # Also exclude if only markdown or doc files were touched
        non_doc_files = [
            f
            for f in changed_files
            if not re.search(r"\.(md|txt|gitignore|yml|yaml|json)$", f)
        ]
        if non_doc_files:
            return True

    return False


def main():
    try:
        # Get the repository name that triggered the pipeline
        print(f"\nProcessing repository: {GITHUB_REPO_NAME}")

        # Get the commit date from the latest commit
        commit_url = (
            f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/commits"
        )
        commit_response = requests.get(
            commit_url,
            headers={"Authorization": f"token {GITHUB_API_TOKEN}"},
            timeout=30,
        )
        print(f"\nCommit url: {commit_url}")
        print(commit_response.content)

        if commit_response.status_code != 200:
            print(
                f"Failed to fetch commits for {GITHUB_REPO_NAME}. Status code: {commit_response.status_code}"
            )
            return

        commit_data = commit_response.json()
        if not commit_data:
            print(f"No commits found for {GITHUB_REPO_NAME}. Exiting.")
            return

        commit_no = 0
        if commit_data[commit_no]["author"]["login"] == "actions":
            commit_no += 1

        diff = get_commit_diff(commit_data[commit_no]["sha"])
        commit_msg = commit_data[commit_no]["commit"]["message"]

        if not is_substantial_change(diff, commit_msg):
            print(f"\nCommit url: {commit_url}")
            return

        commit_date = commit_data[0]["commit"]["author"]["date"]
        publish_date = datetime.fromisoformat(commit_date).strftime("%Y-%m-%dT%H:%M:%S")
        print(f"Commit date for {GITHUB_REPO_NAME}: {publish_date}")

        # Get release links (RPM, DEB, etc.)e
        release_links = get_release_links()

        prompt = generate_blog_post_prompt(release_links, diff, publish_date)

        # Generate description using OpenAI
        title, description, image_idea, youtube_topics = (
            generate_description_with_media(prompt)
        )
        if not title or not description:
            print(
                f"Error generating title/description for {GITHUB_REPO_NAME}. Exiting."
            )
            return

        # Prepare the SEO excerpt
        excerpt = strip_html_tags(clean_html_code_block(description)).strip()
        excerpt = excerpt[
            :150
        ].strip()  # Use the first 150 characters as an SEO excerpt

        # Search for an image and upload it to WordPress
        unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
        image_url = None
        if image_idea and unsplash_key:
            print("Unsplash searching for image")
            raw_img_url = search_image_url_unsplash(image_idea, unsplash_key)
            if raw_img_url:
                print("Unsplash found image")
                image_url = upload_image_to_wordpress(raw_img_url, title + ".jpg")

        # Search for a YouTube video
        youtube_key = os.getenv("YOUTUBE_API")
        video_url = None
        if youtube_topics and youtube_key:
            print("Fetching youtube video")
            for topic in youtube_topics:
                video_url = search_youtube_video(topic, youtube_key)
                if video_url:
                    print("Got youtube video")
                    break

        # Append YouTube enrichment to the description
        description = append_enrichment_to_post(description, video_url)

        # Create WordPress post
        post_response = create_wordpress_post(
            title, description, publish_date, excerpt, featured_image_url=image_url
        )
        if post_response:
            print(
                f"Created post for {GITHUB_REPO_NAME}: {post_response.get('link', 'No link available')}"
            )
        else:
            print(f"Failed to create post for {GITHUB_REPO_NAME}.")

    except Exception as e:
        print(f"An error occurred in the main process: {e}")


if __name__ == "__main__":
    main()
