import io
import os
import re
import uuid

import mysql.connector
import pytest
from PIL import Image

from sportstore import create_app

CFG = {
    "host": os.environ.get("TEST_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("TEST_MYSQL_PORT", "3307")),
    "user": os.environ.get("TEST_MYSQL_USER", "root"),
    "password": os.environ.get("TEST_MYSQL_PASSWORD", ""),
}


@pytest.fixture()
def app():
    name = "web_test_" + uuid.uuid4().hex[:8]
    app = create_app({"MYSQL": dict(CFG, database=name), "SECRET_KEY": "test", "TESTING": True}, load_env=False)
    yield app
    conn = mysql.connector.connect(host=CFG["host"], port=CFG["port"], user=CFG["user"], password=CFG["password"])
    conn.cursor().execute(f"DROP DATABASE IF EXISTS `{name}`")
    conn.close()


class Client:
    def __init__(self, app):
        self.c = app.test_client()
        self.app = app

    def token(self):
        html = self.c.get("/healthz-page-token" if False else "/").get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        if kw.pop("csrf", True):
            data.setdefault("csrf_token", self.token())
        return self.c.post(url, data=data, **kw)

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def register(self, name, pw="secret123"):
        return self.post("/register", {"username": name, "password": pw, "password2": pw})

    def login(self, name, pw="secret123"):
        return self.post("/login", {"username": name, "password": pw})


@pytest.fixture()
def client(app):
    return Client(app)


@pytest.fixture()
def admin(app):
    c = Client(app)
    assert c.register("admin").status_code == 302  # первый пользователь — админ
    return c


@pytest.fixture()
def user(app, admin):
    c = Client(app)
    assert c.register("alice").status_code == 302
    return c


def png_bytes(size=(1200, 800), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(buf, "PNG")
    buf.seek(0)
    return buf
