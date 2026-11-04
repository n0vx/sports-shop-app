"""Слой данных поверх MySQL. Пул соединений: каждое обращение берёт соединение на время запроса."""

import hashlib
import hmac
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

import mysql.connector
from mysql.connector import errorcode, pooling

from .constants import (BONUS_RATE, DB_NAME_RE, MAX_BONUS_SHARE, SEED_PRODUCTS, WELCOME_BONUS)

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")  # общий файл для десктопной и веб-версии
Error = mysql.connector.Error


class DatabaseUnavailable(RuntimeError):
    """Не удалось подключиться к MySQL; текст можно показывать пользователю."""


def friendly_db_error(exc, cfg=None):
    """Понятное сообщение об ошибке MySQL."""
    errno = getattr(exc, "errno", None)
    host = f"{cfg['host']}:{cfg['port']}" if cfg else "серверу"
    if errno in (2003, 2002, 2005, 2006, 2013, 2055):
        return (f"Не удалось подключиться к MySQL ({host}). Проверьте, что сервер запущен, "
                f"а адрес и порт указаны верно.")
    if errno == 1045:
        return "MySQL отклонил логин или пароль."
    if errno == 1044:
        return "У этого пользователя нет прав на указанную базу данных."
    if errno == 1049:
        return "Базы данных с таким именем нет, а прав на её создание у пользователя нет."
    return f"Ошибка MySQL: {exc}"


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)


def _like(text):
    """Экранирует спецсимволы LIKE, чтобы поиск по «50%» искал именно «50%»."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def image_token(ver):
    """Версия фото для URL: меняется при каждой замене, поэтому браузер может кэшировать фото навсегда."""
    return ver.strftime("%Y%m%d%H%M%S%f") if isinstance(ver, datetime) else (str(ver) if ver else None)


class Database:
    # image_ver — версия фото (NULL, если фото нет); сами байты не тянем, пока они не понадобятся
    PRODUCT_SELECT = ("SELECT p.*, i.updated_at AS image_ver FROM products p "
                      "LEFT JOIN product_images i ON i.product_id = p.id")

    def __init__(self, cfg, seed=True, pool_size=8):
        self.cfg = cfg
        if not DB_NAME_RE.match(cfg["database"]):
            raise DatabaseUnavailable("Имя базы: только латиница, цифры и _ (до 64 символов)")
        base = dict(host=cfg["host"], port=int(cfg["port"]), user=cfg["user"], password=cfg["password"],
                    charset="utf8mb4", collation="utf8mb4_unicode_ci", connection_timeout=8, autocommit=True)
        try:
            self._ensure_database(base)
            self._pool = pooling.MySQLConnectionPool(
                pool_name="ss" + uuid.uuid4().hex[:12], pool_size=pool_size, pool_reset_session=False,
                database=cfg["database"], **base)
            self._init_schema()
            if seed and self._one("SELECT COUNT(*) AS n FROM products")["n"] == 0:
                with self._conn() as cnx:
                    cur = cnx.cursor()
                    cur.executemany(
                        "INSERT INTO products(name, category, price, stock, emoji) VALUES (%s,%s,%s,%s,%s)",
                        SEED_PRODUCTS)
                    cur.close()
        except Error as exc:
            raise DatabaseUnavailable(friendly_db_error(exc, cfg)) from exc

    def _ensure_database(self, base):
        """Если базы нет — пробуем создать (нужны права; иначе будет понятная ошибка)."""
        try:
            mysql.connector.connect(database=self.cfg["database"], **base).close()
            return
        except Error as exc:
            if exc.errno != errorcode.ER_BAD_DB_ERROR:
                raise
        conn = mysql.connector.connect(**base)
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE `{self.cfg['database']}` CHARACTER SET utf8mb4 "
                    f"COLLATE utf8mb4_unicode_ci")
        cur.close()
        conn.close()

    def _init_schema(self):
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            text = "\n".join(line for line in fh if not line.lstrip().startswith("--"))
        with self._conn() as cnx:
            cur = cnx.cursor()
            for statement in text.split(";"):
                if statement.strip():
                    cur.execute(statement)
            cur.close()

    def close(self):
        try:
            self._pool._remove_connections()
        except Exception:
            pass

    # ----- служебное
    @contextmanager
    def _conn(self):
        deadline = time.monotonic() + 5
        while True:
            try:
                cnx = self._pool.get_connection()
                break
            except pooling.PoolError:  # все соединения заняты — коротко ждём
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.03)
        try:
            yield cnx
        finally:
            cnx.close()  # возвращает соединение в пул

    def _all(self, sql, params=()):
        with self._conn() as cnx:
            cur = cnx.cursor(dictionary=True)
            try:
                cur.execute(sql, params)
                return cur.fetchall()
            finally:
                cur.close()

    def _one(self, sql, params=()):
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _run(self, sql, params=()):
        with self._conn() as cnx:
            cur = cnx.cursor()
            try:
                cur.execute(sql, params)
                return cur.lastrowid
            finally:
                cur.close()

    def ping(self):
        return self._one("SELECT 1 AS ok")["ok"] == 1

    # ----- пользователи
    def user_count(self):
        return self._one("SELECT COUNT(*) AS n FROM users")["n"]

    def get_user(self, user_id):
        return self._one("SELECT * FROM users WHERE id=%s", (user_id,))

    def register(self, username, password):
        """Первый зарегистрированный пользователь становится администратором."""
        is_first = self.user_count() == 0
        salt = os.urandom(16)
        try:
            new_id = self._run(
                "INSERT INTO users(username, pw_hash, salt, role, bonuses) VALUES (%s,%s,%s,%s,%s)",
                (username.lower(), hash_password(password, salt), salt,
                 "admin" if is_first else "customer", 0 if is_first else WELCOME_BONUS))
        except mysql.connector.IntegrityError:
            raise ValueError("Этот логин уже занят")
        return self.get_user(new_id)

    def authenticate(self, username, password):
        row = self._one("SELECT * FROM users WHERE username=%s", (username.lower(),))
        if row is None:
            # одинаковое время ответа для существующего и несуществующего логина
            hash_password(password, b"\0" * 16)
            return None
        expected = hash_password(password, bytes(row["salt"]))
        return row if hmac.compare_digest(bytes(row["pw_hash"]), expected) else None

    def set_user_appearance(self, user_id, theme, accent):
        self._run("UPDATE users SET theme=%s, accent=%s WHERE id=%s", (theme, accent, user_id))

    # ----- товары
    @staticmethod
    def _decorate(rows):
        for r in rows:
            r["image_token"] = image_token(r.get("image_ver"))
        return rows

    def catalog(self, category=None, query=None, sort="popular"):
        where, params = [], []
        if category:
            where.append("p.category = %s")
            params.append(category)
        if query:
            like = "%" + _like(query) + "%"
            where.append("(p.name LIKE %s OR p.category LIKE %s)")
            params += [like, like]
        order = {"price_asc": "p.price ASC, p.id", "price_desc": "p.price DESC, p.id",
                 "name": "p.name ASC, p.id"}.get(sort, "p.id")
        sql = self.PRODUCT_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY " + order
        return self._decorate(self._all(sql, params))

    def get_product(self, product_id):
        row = self._one(self.PRODUCT_SELECT + " WHERE p.id=%s", (product_id,))
        return self._decorate([row])[0] if row else None

    def products_by_ids(self, ids):
        ids = [int(i) for i in ids]
        if not ids:
            return {}
        rows = self._all(self.PRODUCT_SELECT + " WHERE p.id IN (%s)" % ",".join(["%s"] * len(ids)), ids)
        return {r["id"]: r for r in self._decorate(rows)}

    def save_product(self, product_id, name, category, price, stock, emoji):
        """Создаёт или обновляет товар и возвращает его id."""
        if product_id is None:
            return self._run("INSERT INTO products(name, category, price, stock, emoji) VALUES (%s,%s,%s,%s,%s)",
                             (name, category, price, stock, emoji))
        self._run("UPDATE products SET name=%s, category=%s, price=%s, stock=%s, emoji=%s WHERE id=%s",
                  (name, category, price, stock, emoji, product_id))
        return product_id

    def delete_product(self, product_id):
        self._run("DELETE FROM products WHERE id=%s", (product_id,))  # фото удалится каскадом

    # ----- фото товаров
    def set_product_image(self, product_id, data):
        """Сохраняет (или заменяет) фото. Новая версия ставится автоматически."""
        self._run("REPLACE INTO product_images(product_id, data, updated_at) VALUES (%s,%s,NOW(6))",
                  (product_id, data))

    def remove_product_image(self, product_id):
        self._run("DELETE FROM product_images WHERE product_id=%s", (product_id,))

    def get_image(self, product_id):
        """(версия, байты JPEG) или None."""
        row = self._one("SELECT updated_at AS ver, data FROM product_images WHERE product_id=%s", (product_id,))
        return (row["ver"], bytes(row["data"])) if row else None

    # ----- бюджет организации
    def budget_balance(self):
        row = self._one("SELECT balance FROM budget WHERE id=1")
        return int(row["balance"]) if row else 0

    def budget_entries(self, limit=50):
        return self._all(
            "SELECT e.*, u.username, p.name AS product_name FROM budget_entries e "
            "LEFT JOIN users u ON u.id = e.user_id LEFT JOIN products p ON p.id = e.product_id "
            "ORDER BY e.id DESC LIMIT %s", (int(limit),))

    def budget_change(self, delta, kind, note, user_id, product_id=None, qty=None):
        """Меняет остаток и пишет журнал одной транзакцией. Тратить больше остатка нельзя.

        Если задан product_id (закупка), остаток товара на складе увеличивается на qty в той же транзакции.
        Возвращает новый остаток бюджета.
        """
        if not delta:
            raise ValueError("Сумма должна быть больше нуля")
        with self._conn() as cnx:
            cur = cnx.cursor(dictionary=True)
            try:
                cnx.start_transaction()
                cur.execute("SELECT balance FROM budget WHERE id=1 FOR UPDATE")
                row = cur.fetchone()
                balance = int(row["balance"]) if row else 0
                if balance + delta < 0:
                    raise ValueError(f"Недостаточно средств: в бюджете {balance} ₽, нужно {-delta} ₽")
                if product_id is not None:
                    cur.execute("SELECT id FROM products WHERE id=%s FOR UPDATE", (product_id,))
                    if cur.fetchone() is None:
                        raise ValueError("Товар не найден")
                    cur.execute("UPDATE products SET stock = stock + %s WHERE id=%s", (qty, product_id))
                balance += delta
                cur.execute("UPDATE budget SET balance=%s WHERE id=1", (balance,))
                cur.execute(
                    "INSERT INTO budget_entries(kind, amount, balance_after, note, product_id, qty, user_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)", (kind, delta, balance, note, product_id, qty, user_id))
                cnx.commit()
                return balance
            except BaseException:
                try:
                    cnx.rollback()
                except Error:
                    pass
                raise
            finally:
                cur.close()

    # ----- заказы
    def checkout(self, user_id, cart, use_bonuses):
        """Оформляет заказ одной транзакцией. cart: {product_id: qty}.

        Строки пользователя и товаров блокируются (SELECT ... FOR UPDATE), поэтому два покупателя,
        одновременно берущие последний товар, не смогут «продать» его дважды.
        """
        if not cart:
            raise ValueError("Корзина пуста")
        with self._conn() as cnx:
            cur = cnx.cursor(dictionary=True)
            try:
                cnx.start_transaction()
                cur.execute("SELECT id, bonuses FROM users WHERE id=%s FOR UPDATE", (user_id,))
                user = cur.fetchone()
                if user is None:
                    raise ValueError("Аккаунт не найден — войдите заново")
                lines, total = [], 0
                for pid in sorted(cart):  # единый порядок блокировок — без взаимных зависаний
                    qty = cart[pid]
                    cur.execute("SELECT * FROM products WHERE id=%s FOR UPDATE", (pid,))
                    p = cur.fetchone()
                    if p is None:
                        raise ValueError("Один из товаров больше не продаётся — обновите корзину")
                    if p["stock"] < qty:
                        raise ValueError(f"«{p['name']}»: на складе осталось {p['stock']} шт.")
                    lines.append((p, qty))
                    total += p["price"] * qty
                spend = min(user["bonuses"], int(total * MAX_BONUS_SHARE)) if use_bonuses else 0
                paid = total - spend
                earned = int(paid * BONUS_RATE)
                cur.execute("INSERT INTO orders(user_id, total, bonus_spent, bonus_earned) VALUES (%s,%s,%s,%s)",
                            (user_id, total, spend, earned))
                order_id = cur.lastrowid
                for p, qty in lines:
                    cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (qty, p["id"]))
                    cur.execute("INSERT INTO order_items(order_id, product_id, name, price, qty) "
                                "VALUES (%s,%s,%s,%s,%s)", (order_id, p["id"], p["name"], p["price"], qty))
                cur.execute("UPDATE users SET bonuses = bonuses - %s + %s WHERE id=%s", (spend, earned, user_id))
                cnx.commit()
            except BaseException:
                try:
                    cnx.rollback()
                except Error:
                    pass
                raise
            finally:
                cur.close()
        return dict(order_id=order_id, total=total, spent=spend, paid=paid, earned=earned)

    def orders(self, user_id, limit=30):
        """Последние заказы пользователя с составом (двумя запросами, а не N+1)."""
        orders = self._all("SELECT * FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                           (user_id, int(limit)))
        return self._attach_items(orders)

    def get_order(self, order_id, user_id):
        """Заказ с составом; чужой заказ не отдаётся."""
        row = self._one("SELECT * FROM orders WHERE id=%s AND user_id=%s", (order_id, user_id))
        return self._attach_items([row])[0] if row else None

    def _attach_items(self, orders):
        if not orders:
            return orders
        ids = [o["id"] for o in orders]
        items = self._all("SELECT order_id, product_id, name, price, qty FROM order_items WHERE order_id IN (%s) "
                          "ORDER BY id" % ",".join(["%s"] * len(ids)), ids)
        by_order = {}
        for it in items:
            by_order.setdefault(it["order_id"], []).append(it)
        for o in orders:
            o["items"] = by_order.get(o["id"], [])
            o["paid"] = o["total"] - o["bonus_spent"]
        return orders
