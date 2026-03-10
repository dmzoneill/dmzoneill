import os
import sys

import requests


def main():
    if len(sys.argv) != 2:
        print("Usage: python telegram-notify.py <message>")
        sys.exit(1)

    message = sys.argv[1]

    # Remove "dmzoneill/" prefix if present
    message = message.replace("dmzoneill/", "")
    print(message)

    # Configuration
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
    }

    try:
        resp = requests.post(url, json=payload)
        if resp.status_code == 429:
            print(f"Telegram rate limited (429): {resp.text}")
            sys.exit(0)
        resp.raise_for_status()
        print(f"Telegram response: {resp.json()}")
    except Exception as e:
        print(f"Error sending message: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
