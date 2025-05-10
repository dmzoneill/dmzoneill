import sys
import os
import requests
import json
import base64

def main():
    if len(sys.argv) != 2:
        print("Usage: python send_webdis_message.py <message>")
        sys.exit(1)

    message = sys.argv[1]

    # Configuration
    host = os.getenv("REDIS_HOST", "185.219.84.242")
    port = os.getenv("REDIS_PORT", "6380")
    password = os.getenv("REDIS_PASSWORD")

    url = f"http://{host}:{port}/EXEC"
    payload = json.dumps(["RPUSH", "fio", message])
    headers = {"Content-Type": "application/json"}

    if password:
        token = base64.b64encode(f"{password}:".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    try:
        resp = requests.post(url, data=payload, headers=headers)
        resp.raise_for_status()
        print(f"Webdis response: {resp.text}")
    except Exception as e:
        print(f"Error sending message: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
