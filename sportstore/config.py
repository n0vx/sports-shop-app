"""Настройки из переменных окружения (и файла .env рядом с проектом). Переменные окружения важнее файла."""

import os

from dotenv import load_dotenv

MYSQL_DEFAULTS = {"host": "127.0.0.1", "port": 3306, "user": "root", "password": "", "database": "sport_store"}


def _flag(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def load_config(overrides=None, use_env_file=True):
    if use_env_file:
        load_dotenv()
    env = os.environ
    mysql_cfg = dict(MYSQL_DEFAULTS)
    for key in mysql_cfg:
        value = env.get("SPORT_STORE_MYSQL_" + key.upper())
        if value is not None:
            mysql_cfg[key] = value
    try:
        mysql_cfg["port"] = int(mysql_cfg["port"])
    except (TypeError, ValueError):
        mysql_cfg["port"] = 3306
    cfg = {
        "MYSQL": mysql_cfg,
        "SECRET_KEY": env.get("SECRET_KEY") or None,
        "HTTPS": _flag(env.get("SPORT_STORE_HTTPS")),    # сайт открыт по https: cookie только по защищённому каналу
        "BEHIND_PROXY": _flag(env.get("SPORT_STORE_PROXY")),  # за nginx/другим прокси: доверять X-Forwarded-*
    }
    for key, value in (overrides or {}).items():
        if key == "MYSQL":
            cfg["MYSQL"].update(value)
        else:
            cfg[key] = value
    return cfg
