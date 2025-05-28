import sys
import os
import requests
import base64


def main():
    if len(sys.argv) != 2:
        print("Usage: python redis-notify.py <message>")
        sys.exit(1)

    message = sys.argv[1]

    # Remove "dmzoneill/" prefix if present
    message = message.replace("/dmzoneill", "")

    # Configuration
    host = os.getenv("REDIS_HOST", "185.219.84.242")
    port = os.getenv("REDIS_PORT", "6380")
    password = os.getenv("REDIS_PASSWORD")

    url = f"http://{host}:{port}/"
    headers = {"Content-Type": "text/plain"}

    if password:
        token = base64.b64encode(f"{password}:".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    payload = f"RPUSH/fio/{message}"

    try:
        resp = requests.post(url, data=payload.encode(), headers=headers)
        resp.raise_for_status()
        print(f"Webdis response: {resp.text}")
    except Exception as e:
        print(f"Error sending message: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
