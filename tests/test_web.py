import io

from conftest import Client, png_bytes


def test_pages_and_headers(client, admin):
    r = client.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/healthz").status_code == 200
    assert client.get("/nope").status_code == 404


def test_first_user_is_admin_and_welcome_bonus(app, admin, user):
    assert admin.get("/profile").status_code == 200
    db = app.extensions["db"]
    assert db.get_user(1)["role"] == "admin"
    assert db.get_user(2)["role"] == "customer"
    assert db.get_user(2)["bonuses"] == 500


def test_register_validation_and_duplicates(client, admin):
    assert client.register("a").status_code == 422
    assert client.post("/register", {"username": "bob", "password": "secret123", "password2": "x"}).status_code == 422
    assert client.register("bob").status_code == 302
    assert Client(client.app).register("BOB").status_code == 422


def test_csrf_required(client, admin):
    r = client.post("/login", {"username": "admin", "password": "secret123"}, csrf=False)
    assert r.status_code == 400


def test_login_logout_and_wrong_password(app, admin):
    c = Client(app)
    assert c.login("admin", "bad").status_code == 401
    assert c.login("admin").status_code == 302
    assert c.get("/profile").status_code == 200
    c.post("/logout")
    assert c.get("/profile").status_code == 302


def test_login_throttling(app, admin):
    c = Client(app)
    codes = [c.login("admin", "bad").status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429
    assert c.login("admin").status_code == 429  # и верный пароль блокируется


def test_open_redirect_blocked(app, admin):
    c = Client(app)
    r = c.post("/login?next=//evil.com", {"username": "admin", "password": "secret123"})
    assert r.status_code == 302 and "evil.com" not in r.headers["Location"]


def test_catalog_filters(admin):
    html = admin.get("/?cat=Обувь").get_data(as_text=True)
    assert "Обувь" in html
    assert "Кроссовки" in admin.get("/?q=кросс").get_data(as_text=True)
    assert "Ничего не найдено" in admin.get("/?q=%25%25zzz").get_data(as_text=True)
    asc = admin.get("/?sort=price_asc").get_data(as_text=True)
    assert asc and admin.get("/?sort=garbage").status_code == 200


def test_search_xss_escaped(admin):
    html = admin.get("/?q=<script>alert(1)</script>").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html


def test_cart_and_checkout_with_bonuses(app, user):
    db = app.extensions["db"]
    p = db.catalog()[0]
    assert user.post(f"/cart/add/{p['id']}").status_code == 302
    r = user.post(f"/cart/add/{p['id']}", headers={"Accept": "application/json", "X-Requested-With": "fetch"})
    assert r.get_json()["count"] == 2
    before_stock = db.get_product(p["id"])["stock"]
    r = user.post("/cart/checkout", {"use_bonus": "1"})
    assert r.status_code == 302 and "/orders/" in r.headers["Location"]
    assert db.get_product(p["id"])["stock"] == before_stock - 2
    me = db.get_user(2)
    total = p["price"] * 2
    spent = min(500, int(total * 0.30))
    assert me["bonuses"] == 500 - spent + int((total - spent) * 0.05)
    assert user.get(r.headers["Location"]).status_code == 200
    assert user.get("/cart").status_code == 200


def test_cannot_exceed_stock_and_checkout_needs_login(app, client, admin):
    db = app.extensions["db"]
    p = db.catalog()[0]
    db.save_product(p["id"], p["name"], p["category"], p["price"], 1, p.get("emoji") or "🏅")
    assert client.post(f"/cart/add/{p['id']}").status_code == 302
    r = client.post(f"/cart/add/{p['id']}", headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409
    assert client.post("/cart/checkout").status_code == 302  # на вход


def test_other_users_order_not_visible(app, user):
    db = app.extensions["db"]
    p = db.catalog()[0]
    user.post(f"/cart/add/{p['id']}")
    oid = user.post("/cart/checkout").headers["Location"].rsplit("/", 1)[1]
    other = Client(app)
    other.register("mallory")
    assert other.get(f"/orders/{oid}").status_code == 404


def test_admin_only(app, user, client):
    assert client.get("/admin/products/new").status_code == 302
    assert user.get("/admin/products/new").status_code == 403
    assert user.post("/admin/products/1/delete").status_code == 403
    assert user.post("/admin/products/1/photo", {"photo": (png_bytes(), "a.png")},
                     content_type="multipart/form-data").status_code == 403


def test_admin_product_crud(app, admin):
    r = admin.post("/admin/products/new", {"name": "Мяч", "category": "Тренажёры и инвентарь", "price": "990",
                                           "stock": "5", "emoji": "⚽"})
    assert r.status_code == 302
    db = app.extensions["db"]
    p = [x for x in db.catalog(query="Мяч")][0]
    assert p["price"] == 990
    bad = admin.post("/admin/products/new", {"name": "x", "category": "Обувь", "price": "-1", "stock": "a"})
    assert bad.status_code == 422
    admin.post(f"/admin/products/{p['id']}/edit", {"name": "Мяч Pro", "category": "Обувь", "price": "1200", "stock": "2"})
    assert db.get_product(p["id"])["name"] == "Мяч Pro"
    assert admin.post(f"/admin/products/{p['id']}/delete").status_code == 302
    assert db.get_product(p["id"]) is None


def test_photo_upload_serve_etag_and_delete(app, admin):
    db = app.extensions["db"]
    pid = db.catalog()[0]["id"]
    r = admin.post(f"/admin/products/{pid}/photo", {"photo": (png_bytes(), "a.png")},
                   content_type="multipart/form-data")
    assert r.status_code == 302
    page = admin.get("/").get_data(as_text=True)
    assert f"/product/{pid}/photo?v=" in page
    img = admin.get(f"/product/{pid}/photo")
    assert img.mimetype == "image/jpeg" and img.headers["ETag"]
    from PIL import Image
    assert max(Image.open(io.BytesIO(img.data)).size) <= 1000
    again = admin.get(f"/product/{pid}/photo", headers={"If-None-Match": img.headers["ETag"]})
    assert again.status_code == 304
    admin.post(f"/admin/products/{pid}/photo/delete")
    assert admin.get(f"/product/{pid}/photo").status_code == 404


def test_photo_rejects_garbage(app, admin):
    pid = app.extensions["db"].catalog()[0]["id"]
    r = admin.post(f"/admin/products/{pid}/photo", {"photo": (io.BytesIO(b"not an image"), "a.png")},
                   content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert app.extensions["db"].get_image(pid) is None


def test_appearance_saved_per_user(app, user):
    r = user.post("/appearance", headers={"Accept": "application/json"},
                  data=None) if False else user.c.post(
        "/appearance", json={"theme": "dark", "accent": "#1E88E5"}, headers={"X-CSRF-Token": user.token()})
    d = r.get_json()
    assert d["ok"] and d["theme"] == "dark" and "--accent" in d["vars"]
    assert 'data-theme="dark"' in user.get("/").get_data(as_text=True)
    assert app.extensions["db"].get_user(2)["theme"] == "dark"
    again = Client(app)
    again.login("alice")
    assert 'data-theme="dark"' in again.get("/").get_data(as_text=True)
    bad = user.c.post("/appearance", json={"accent": "javascript:1"}, headers={"X-CSRF-Token": user.token()})
    assert bad.status_code == 400
