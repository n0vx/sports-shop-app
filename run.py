"""Запуск веб-версии:  python run.py   (для продакшена: gunicorn "run:app")."""
import os
import sys

from sportstore import DatabaseUnavailable, create_app

try:
    app = create_app()
except DatabaseUnavailable as exc:
    sys.exit(f"Не удалось подключиться к MySQL: {exc}\nПроверьте настройки в .env (см. .env.example).")

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
