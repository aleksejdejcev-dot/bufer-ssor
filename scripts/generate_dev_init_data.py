#!/usr/bin/env python3
"""
CLI-инструмент для генерации тестового подписанного Telegram initData.
Используется ТОЛЬКО для локальной разработки и ручного тестирования API.
НЕ является частью FastAPI сервера.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import urlencode


def load_bot_token() -> str:
    # Ищем токен в системном окружении или в файлах .env / backend/.env
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        return token

    for env_path in [".env", "../.env", "backend/.env"]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        val = line.split("TELEGRAM_BOT_TOKEN=")[1].strip()
                        if val:
                            return val
    return ""


def generate_init_data(user_id: int, first_name: str, username: str, bot_token: str) -> str:
    if not bot_token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не задан ни в окружении, ни в .env", file=sys.stderr)
        sys.exit(1)

    user_data = json.dumps(
        {"id": user_id, "first_name": first_name, "username": username},
        separators=(",", ":"),
    )
    now = int(time.time())
    params = {
        "auth_date": str(now),
        "query_id": f"AAHdF6IQAAAAAN0XohDZz{user_id}",
        "user": user_data,
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = h
    return urlencode(params)


def main():
    parser = argparse.ArgumentParser(description="Скрипт создания тестового initData Telegram")
    parser.add_argument("--user-id", type=int, default=999001, help="ID пользователя Telegram (default: 999001)")
    parser.add_argument("--name", type=str, default="Тестовый Партнер", help="Имя пользователя")
    parser.add_argument("--username", type=str, default="test_user", help="Username")
    args = parser.parse_args()

    token = load_bot_token()
    init_data = generate_init_data(args.user_id, args.name, args.username, token)
    print(init_data)


if __name__ == "__main__":
    main()
