import os
import requests
import base64
import re
from datetime import datetime
import json


# GitHub API token (keep it secure)
GITHUB_API_TOKEN = os.getenv("PROFILE_HOOK")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_RUN_ID = os.getenv('GITHUB_RUN_ID')
GITHUB_REPO_NAME = os.getenv("GITHUB_REPOSITORY").split("/")[1]

# WordPress API details
WORDPRESS_URL = os.getenv("WORDPRESS_URL")
WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME")
WORDPRESS_PASSWORD = os.getenv("WORDPRESS_PASSWORD")
WORDPRESS_APPLICATION = os.getenv("WORDPRESS_APPLICATION")

print(GITHUB_USER)
print(GITHUB_RUN_ID)
print(GITHUB_REPO_NAME)

class OpenAIProvider():

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
            # Catch any request-related exceptions (e.g., network issues, timeouts)
            raise Exception(f"Request failed: {str(e)}")


# Fetch GitHub Release Link and associated assets (such as RPM, DEB)
def get_github_release():
    release_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/releases/latest"
    release_response = requests.get(release_url, headers={'Authorization': f'token {GITHUB_API_TOKEN}'})

    if release_response.status_code == 200:
        release_data = release_response.json()
        
        # Find assets (deb, rpm, etc.) from the release
        assets = release_data.get('assets', [])
        release_links = {
            'github_release': release_data.get('html_url', 'Not available'),
            'assets': {}
        }

        # Look through assets and find deb, rpm files
        for asset in assets:
            if '.deb' in asset['name']:
                release_links['assets']['deb'] = asset['browser_download_url']
            if '.rpm' in asset['name']:
                release_links['assets']['rpm'] = asset['browser_download_url']

        return release_links
    else:
        print(f"Failed to fetch release details for {GITHUB_REPO_NAME}.")
        return {}

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
    
    headers = {
        'Authorization': f'token {GITHUB_API_TOKEN}'
    }

    # Get all jobs for the given pipeline run
    response = requests.get(workflow_runs_url, headers=headers)

    if response.status_code == 200:
        jobs = response.json().get("jobs", [])

        # Find the specific job that corresponds to the provided job_name
        for job in jobs:
            if job['name'].lower() == job_name.lower():

                # Get the job ID and use it to fetch the logs
                job_id = job['id']
                log_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/actions/jobs/{job_id}/logs"

                # Fetch logs for the specific job using its job_id
                log_response = requests.get(log_url, headers=headers)

                if log_response.status_code == 200:
                    logs = log_response.text  # Logs are plain text, not JSON

                    # If no pattern is provided, return logs as is
                    if not pattern:
                        return logs

                    # Search for the pattern in the log output
                    match = re.search(pattern, logs)

                    if match:
                        return match.group(1)  # Return the matched group (the URL or information)
                    else:
                        print(f"Pattern not found in the logs for job {job_name}.")
                        return None
                else:
                    print(f"Failed to fetch logs for job {job_name}. Status Code: {log_response.status_code}")
                    return None
    else:
        print(f"Failed to fetch workflow jobs. Status Code: {response.status_code}")
        return None

# Fetch the programming languages used in the GitHub repo
def get_github_languages():
    languages_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/languages"
    languages_response = requests.get(languages_url, headers={'Authorization': f'token {GITHUB_API_TOKEN}'})
    
    if languages_response.status_code == 200:
        languages_data = languages_response.json()
        # Return a list of programming languages used in the repository
        return list(languages_data.keys())
    else:
        print(f"Failed to fetch programming languages for {GITHUB_REPO_NAME}.")
        return []

# Example function to get the release links
# Example function to get the release links
def get_release_links():
    release_links = {}

    # Get GitHub Release Link and Assets
    release_data = get_github_release()
    if release_data:
        release_links['github_release'] = release_data.get('github_release', 'Not available')
        release_links['assets'] = release_data.get('assets', {})

    # Fetch PyPI URL from the logs
    pypi_url = get_release_url(job_name="cicd / Pypi publish", pattern=r'(https://pypi\.org/project/[^/]+/\S+)')
    if pypi_url:
        release_links['pypi'] = pypi_url
    else:
        print("Failed to retrieve PyPI URL.")

    # Fetch Docker Hub or GCR URL from the logs (using a pattern for pushing manifest)
    docker_url = get_release_url(job_name="cicd / Docker publish", pattern=r'pushing manifest for s*(docker.*)')
    if docker_url:
        release_links['docker_hub'] = docker_url
    else:
        print("Failed to retrieve Docker Push URL.")

    # Fetch Docker Hub or GCR URL from the logs (using a pattern for pushing manifest)
    docker_url = get_release_url(job_name="cicd / Docker publish", pattern=r'pushing manifest for s*(ghcr.*)')
    if docker_url:
        release_links['ghcr_hub'] = docker_url
    else:
        print("Failed to retrieve GHCR Push URL.")

    
    return release_links

# Function to remove enclosing code block markers (like ```html, ```)
def clean_html_code_block(content):
    content = re.sub(r"^```.*?$", "", content, flags=re.MULTILINE)  # Remove start of code block
    content = re.sub(r"```$", "", content)  # Remove end of code block
    return content

# Function to strip HTML tags from a string (for title and excerpt)
def strip_html_tags(text):
    return re.sub(r'<[^>]*>', '', text)

# Fetch GitHub Release Link and associated assets (such as RPM, DEB)
def get_github_release():
    release_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/releases/latest"
    release_response = requests.get(release_url, headers={'Authorization': f'token {GITHUB_API_TOKEN}'})

    if release_response.status_code == 200:
        release_data = release_response.json()
        
        # Getting the GitHub release URL
        github_release_url = release_data.get('html_url', 'Not available')  # Release URL
        
        # Find assets (deb, rpm, etc.) from the release
        assets = release_data.get('assets', [])
        release_links = {
            'github_release': github_release_url,
            'assets': {}
        }

        # Look through assets and find deb, rpm files
        for asset in assets:
            if '.deb' in asset['name']:
                release_links['assets']['deb'] = asset['browser_download_url']
            if '.rpm' in asset['name']:
                release_links['assets']['rpm'] = asset['browser_download_url']

        return release_links
    else:
        print(f"Failed to fetch release details for {GITHUB_REPO_NAME}.")
        return {}


# Generate description using OpenAI
def generate_description(prompt):
    user_prompt = f"Please include a title for the post.\n\n"
    user_prompt += prompt
    ai_provider = OpenAIProvider()

    system_prompt = """
    Generate a blog post based on the following release diff and provide an analysis of the changes:

    Summarize the files and lines changed in the provided diff.

    Provide insights on the impact of these changes, focusing on potential improvements in code quality, flexibility, and functionality.

    Highlight any bug fixes, refactoring, or feature enhancements.

    Mention if there are any modifications in dependencies, configurations, or testing practices.

    Include the release information and any relevant download or installation links for the new version.

    ** You must output in HTML only and it must be comptaible with wordpress **
    ** At the topic put 'Title: (Generate a short descriptive title)' **
    ** ALL URLs must be valid for images and hyperlinks. **
    ** The github user page is https://github.com/dmzoneill/ **
    ** Dont use HTML comments <!---- comment ---/> in the output **
    ** if there are any images used in the README.md of the github repo readme, try incorporate them in the post **
    """

    try:
        response = ai_provider.improve_text(system_prompt, user_prompt)
        
        title_match = re.search(r"Title:\s*(.*)", response)  # Match the title
        if title_match:
            title = title_match.group(1).strip()
            description = re.sub(r"Title:\s*.*\n", "", response).strip()
            return title, description
        else:
            return "Untitled", response.strip()

    except Exception as e:
        print(f"Error generating description: {e}")
        return None, None

# Fetch existing tags from WordPress or create them if they don't exist
def get_or_create_tags(tags):
    tag_ids = []
    tags_url = f"{WORDPRESS_URL}tags"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Basic {base64.b64encode(f"{WORDPRESS_USERNAME}:{WORDPRESS_APPLICATION}".encode()).decode()}'
    }
    
    response = requests.get(tags_url, headers=headers, params={'page': 1, 'per_page': 100})
    if response.status_code == 200:
        existing_tags = response.json()
        existing_tag_names = {tag['name'].lower(): tag['id'] for tag in existing_tags}
        
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower in existing_tag_names:
                tag_ids.append(existing_tag_names[tag_lower])
            else:
                create_tag_url = f"{WORDPRESS_URL}tags"
                create_tag_data = {"name": tag}
                create_response = requests.post(create_tag_url, json=create_tag_data, headers=headers)
                if create_response.status_code == 201:
                    new_tag = create_response.json()
                    tag_ids.append(new_tag['id'])
                else:
                    print(f"Failed to create tag '{tag}'.")
    else:
        print(f"Failed to fetch tags. Status code: {response.status_code}")

    return tag_ids


def get_category_id(languages, categories):
    category_id = []
    
    # Loop through each category and check if any category name matches the programming languages
    for category in categories:
        for language in languages:
            if language.lower() == category['name'].lower():
                category_id = category['id']
                break
    
    return category_id


# Create WordPress post with the given title, content, and tags
def create_wordpress_post(title, content, publish_date, excerpt):
    url = f"{WORDPRESS_URL}posts"
    creds = f"{WORDPRESS_USERNAME}:{WORDPRESS_APPLICATION}".encode()
    creds = base64.b64encode(creds).decode('utf-8')
    headers = {'Content-Type': 'application/json', 'Authorization': f'Basic {creds}'}

    languages = get_github_languages()
    if not languages:
        print(f"No programming languages found for {GITHUB_REPO_NAME}.")
        return None
    
    tag_ids = get_or_create_tags(languages)
    categories_url = f"{WORDPRESS_URL}categories"
    response = requests.get(categories_url, headers=headers, params={'page': 1, 'per_page': 100})
    category_id = ""
    if response.status_code == 200:
        categories = response.json()
        category_id = get_category_id(languages, categories)
        
        if not category_id:
            print(f"No matching categories found for {GITHUB_REPO_NAME}. Using default category.")

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
        "categories": category_id
    }

    try:
        response = requests.post(url, json=post_data, headers=headers)
        if response.status_code == 201:
            print(f"Post created successfully! URL: {response.json()['link']}")
            return response.json()
        else:
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
    if 'deb' in release_links['assets']:
        prompt += f"- Debian Package: {release_links['assets']['deb']}\n"
    if 'rpm' in release_links['assets']:
        prompt += f"- RPM Package: {release_links['assets']['rpm']}\n"
    
    # Additional release links
    if 'chrome_extension' in release_links:
        prompt += f"- Chrome Extension Release: {release_links['chrome_extension']}\n"
    if 'pypi' in release_links:
        prompt += f"- PyPI Release: {release_links['pypi']}\n"
    if 'docker_hub' in release_links:
        prompt += f"- Docker Hub Release: {release_links['docker_hub']}\n"
    if 'ghcr_hub' in release_links:
        prompt += f"- GHCR Release: {release_links['ghcr_hub']}\n"

    return prompt + "\n\nPlease include a title for the post."

def get_commit_diff(sha):
    """
    Fetch the commit diff for a given commit SHA in a repository, including file names in the diff output.

    :param sha: The commit SHA
    :param repo_name: The repository name (e.g., 'username/repository')
    :return: The commit diff as a string, or None if not found
    """
    # GitHub API URL for the commit details (this returns diff information in the files section)
    commit_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/commits/{sha}"
    
    headers = {
        'Authorization': f'token {GITHUB_API_TOKEN}'
    }
    
    # Fetch the commit details
    response = requests.get(commit_url, headers=headers)

    if response.status_code == 200:
        commit_data = response.json()

        # Initialize list to store diffs
        diffs = []

        # Iterate over the files changed in this commit and collect diffs
        for file in commit_data.get('files', []):
            # GitHub provides a diff for each file change
            if 'patch' in file:
                # Format the diff to include file names, as in a typical unified diff
                diff = f"diff --git a/{file['filename']} b/{file['filename']}\n"
                diff += file['patch']  # This contains the diff for that file
                diffs.append(diff)

        if diffs:
            return "\n".join(diffs)  # Combine all diffs for the commit
        else:
            print("No diff data available in the commit.")
            return None
    else:
        print(f"Failed to fetch commit details for SHA {sha}. Status Code: {response.status_code}")
        return None


def main():
    try:
        # Get the repository name that triggered the pipeline
        print(f"\nProcessing repository: {GITHUB_REPO_NAME}")

        # Get the commit date from the latest commit
        commit_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO_NAME}/commits"
        commit_response = requests.get(commit_url, headers={'Authorization': f'token {GITHUB_API_TOKEN}'})
        print(commit_response.content)
        
        if commit_response.status_code != 200:
            print(f"Failed to fetch commits for {GITHUB_REPO_NAME}. Status code: {commit_response.status_code}")
            return
        
        commit_data = commit_response.json()
        if not commit_data:
            print(f"No commits found for {GITHUB_REPO_NAME}. Exiting.")
            return
        
        commit_no = 0
        if commit_data[commit_no]['author']['login'] == "actions":
            commit_no += 1

        diff = get_commit_diff(commit_data[commit_no]['sha'])
        
        commit_date = commit_data[0]['commit']['author']['date']
        publish_date = datetime.fromisoformat(commit_date).strftime('%Y-%m-%dT%H:%M:%S')
        print(f"Commit date for {GITHUB_REPO_NAME}: {publish_date}")

        # Get release links (RPM, DEB, etc.)
        release_links = get_release_links()

        prompt = generate_blog_post_prompt(release_links, diff, publish_date)

        # Generate description using OpenAI
        title, description = generate_description(prompt)
        if not title or not description:
            print(f"Error generating title/description for {GITHUB_REPO_NAME}. Exiting.")
            return

        # Prepare the SEO excerpt
        excerpt = strip_html_tags(clean_html_code_block(description)).strip()
        excerpt = excerpt[:150].strip()  # Use the first 150 characters as an SEO excerpt


        # Create WordPress post
        post_response = create_wordpress_post(title, description, publish_date, excerpt)
        if post_response:
            print(f"Created post for {GITHUB_REPO_NAME}: {post_response.get('link', 'No link available')}")
        else:
            print(f"Failed to create post for {GITHUB_REPO_NAME}.")

    except Exception as e:
        print(f"An error occurred in the main process: {e}")

if __name__ == "__main__":
    main()
