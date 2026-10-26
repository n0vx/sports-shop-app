"""Перенос данных из прежней версии приложения (SQLite, файл store.db) в MySQL.

Использование:
    python migrate_sqlite_to_mysql.py [путь/к/store.db]

Берёт настройки подключения из config.ini (сначала запустите app.py и подключитесь к MySQL один раз).
Переносит пользователей (с паролями), товары, заказы и их состав. Работает только с пустой базой:
если в MySQL уже есть пользователи, товары или заказы, скрипт остановится и ничего не изменит.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # чтобы найти app.py из любого каталога

import app


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(app.APP_DIR, "store.db")
    if not os.path.exists(path):
        print(f"Файл {path} не найден. Укажите путь к старой базе: python {sys.argv[0]} путь/к/store.db")
        return 1
    if app.mysql is None:
        print("Не установлен драйвер MySQL: pip install -r requirements.txt")
        return 1

    cfg = app.Config(app.CONFIG_PATH).mysql()
    try:
        db = app.Database(cfg, seed=False)
    except (app.mysql.connector.Error, ValueError) as exc:
        print("Не удалось подключиться к MySQL:",
              app.friendly_db_error(exc, cfg) if isinstance(exc, app.mysql.connector.Error) else exc)
        print("Запустите app.py и подключитесь через форму — настройки сохранятся в config.ini.")
        return 1

    for table in ("users", "products", "orders", "order_items"):
        if db._one(f"SELECT COUNT(*) AS n FROM {table}")["n"]:
            print(f"В MySQL уже есть данные (таблица {table}). Перенос возможен только в пустую базу.")
            return 1

    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row

    def rows(table):
        return src.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()

    user_cols = {r["name"] for r in src.execute("PRAGMA table_info(users)")}
    counts = {}
    db.conn.start_transaction()
    cur = db.conn.cursor()
    try:
        for u in rows("users"):
            cur.execute(
                "INSERT INTO users(id, username, pw_hash, salt, role, bonuses, theme, accent) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (u["id"], u["username"], bytes(u["pw_hash"]), bytes(u["salt"]), u["role"], u["bonuses"],
                 u["theme"] if "theme" in user_cols else None,
                 u["accent"] if "accent" in user_cols else None))
        counts["пользователей"] = len(rows("users"))
        for p in rows("products"):
            cur.execute("INSERT INTO products(id, name, category, price, stock, emoji) VALUES (%s,%s,%s,%s,%s,%s)",
                        (p["id"], p["name"], p["category"], p["price"], p["stock"], p["emoji"] or ""))
        counts["товаров"] = len(rows("products"))
        for o in rows("orders"):
            created = o["created_at"] if len(o["created_at"]) > 16 else o["created_at"] + ":00"
            cur.execute("INSERT INTO orders(id, user_id, total, bonus_spent, bonus_earned, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (o["id"], o["user_id"], o["total"], o["bonus_spent"], o["bonus_earned"], created))
        counts["заказов"] = len(rows("orders"))
        for i in rows("order_items"):
            cur.execute("INSERT INTO order_items(id, order_id, product_id, name, price, qty) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (i["id"], i["order_id"], i["product_id"], i["name"], i["price"], i["qty"]))
        counts["позиций в заказах"] = len(rows("order_items"))
        db.conn.commit()
    except Exception as exc:
        db.conn.rollback()
        print("Перенос не удался, в MySQL ничего не изменилось:", exc)
        return 1
    finally:
        cur.close()
        src.close()
        db.close()

    print("Готово. Перенесено: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + ".")
    print("Старый файл store.db больше не используется — его можно сохранить как резервную копию.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
