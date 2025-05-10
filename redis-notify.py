import redis
import sys
import os

def main():
    if len(sys.argv) != 2:
        print("Usage: python send_redis_message.py <message>")
        sys.exit(1)

    message = sys.argv[1]

    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "185.219.84.242"),
        port=int(os.getenv("REDIS_PORT", "6380")),
        password=os.getenv("REDIS_PASSWORD"),
        ssl=os.getenv("REDIS_SSL", "false").lower() == "true"
    )

    r.rpush("fio", message)
    print(f"Pushed message to Redis: {message}")

if __name__ == "__main__":
    main()
