-- Схема базы данных SPORT STORE (MySQL 8+ / MariaDB 10.4+).
-- Приложение выполняет этот файл автоматически при запуске (все таблицы создаются «если их нет»),
-- но его можно применить и вручную:  mysql -u USER -p sport_store < schema.sql
--
-- Создание самой базы и отдельного пользователя (выполнить один раз от имени root):
--   CREATE DATABASE sport_store CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
--   CREATE USER 'sport_store'@'localhost' IDENTIFIED BY 'придумайте_пароль';
--   GRANT ALL PRIVILEGES ON sport_store.* TO 'sport_store'@'localhost';

CREATE TABLE IF NOT EXISTS users (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(32)  NOT NULL UNIQUE,
    pw_hash     VARBINARY(32) NOT NULL,
    salt        VARBINARY(32) NOT NULL,
    role        ENUM('customer', 'admin') NOT NULL DEFAULT 'customer',
    bonuses     INT UNSIGNED NOT NULL DEFAULT 0,
    theme       VARCHAR(10)  NULL,
    accent      CHAR(7)      NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS products (
    id        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name      VARCHAR(120) NOT NULL,
    category  VARCHAR(60)  NOT NULL,
    price     INT UNSIGNED NOT NULL,
    stock     INT UNSIGNED NOT NULL DEFAULT 0,
    emoji     VARCHAR(16)  NOT NULL DEFAULT '',
    CONSTRAINT chk_products_price CHECK (price > 0),
    INDEX idx_products_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS orders (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id       INT UNSIGNED NOT NULL,
    total         INT UNSIGNED NOT NULL,
    bonus_spent   INT UNSIGNED NOT NULL,
    bonus_earned  INT UNSIGNED NOT NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users (id),
    INDEX idx_orders_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS order_items (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    order_id    INT UNSIGNED NOT NULL,
    product_id  INT UNSIGNED NULL,
    name        VARCHAR(120) NOT NULL,
    price       INT UNSIGNED NOT NULL,
    qty         INT UNSIGNED NOT NULL,
    CONSTRAINT fk_items_order   FOREIGN KEY (order_id)   REFERENCES orders (id)   ON DELETE CASCADE,
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Фото товаров. Лежат отдельно от products, чтобы список товаров грузился быстро.
-- Приложение само уменьшает фото (до 1000 px по длинной стороне, JPEG), так что строка весит обычно 100–300 КБ.
-- updated_at служит версией: по ней приложения на разных компьютерах понимают, что фото сменили.
CREATE TABLE IF NOT EXISTS product_images (
    product_id  INT UNSIGNED NOT NULL PRIMARY KEY,
    data        MEDIUMBLOB   NOT NULL,
    updated_at  DATETIME(6)  NOT NULL,
    CONSTRAINT fk_images_product FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
