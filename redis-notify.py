import sys
import os
import requests
def main():
    if len(sys.argv) != 2:
        print("Usage: python send_webdis_message.py <message>")
        sys.exit(1)

    message = sys.argv[1]

    # Configuration
    host = os.getenv("REDIS_HOST", "185.219.84.242")
    port = os.getenv("REDIS_PORT", "6380")
    password = os.getenv("REDIS_PASSWORD")
    use_ssl = os.getenv("REDIS_SSL", "true").lower() == "true"
    url_base = f"http://{host}:{port}"

    # Construct the URL
    url = f"{url_base}/rpush/fio"
    headers = {'Authorization': f'Basic {password}:'} if password else {}

    try:
        resp = requests.post(url, data=message.encode(), headers=headers, verify=False)
        resp.raise_for_status()
        print(f"Webdis response: {resp.text}")
    except Exception as e:
        print(f"Error sending message: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
