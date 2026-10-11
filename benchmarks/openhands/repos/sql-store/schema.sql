-- schema.sql — Database schema and seed data for the sql-store demo.

-- -----------------------------------------------------------------------
-- Core tables
-- -----------------------------------------------------------------------

CREATE TABLE customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    email      TEXT    UNIQUE NOT NULL,
    joined_at  TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    product     TEXT    NOT NULL,
    amount      REAL    NOT NULL,
    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    description TEXT,
    price       REAL    NOT NULL,
    stock       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE order_items (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    qty        INTEGER NOT NULL DEFAULT 1,
    unit_price REAL    NOT NULL
);

CREATE TABLE reviews (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    product_id  INTEGER REFERENCES products(id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TEXT    DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------
-- Seed data — customers
-- -----------------------------------------------------------------------

INSERT INTO customers (id, name, email) VALUES
    (1, 'Alice',   'alice@example.com'),
    (2, 'Bob',     'bob@example.com'),
    (3, 'Carol',   'carol@example.com'),
    (4, 'David',   'david@example.com'),
    (5, 'Eva',     'eva@example.com');

-- -----------------------------------------------------------------------
-- Seed data — products
-- -----------------------------------------------------------------------

INSERT INTO products (id, name, description, price, stock) VALUES
    (1, 'Widget',    'A handy widget for everyday use',       29.99, 100),
    (2, 'Gadget',    'High-tech gadget with many features',   49.99,  50),
    (3, 'Doohickey', 'Compact doohickey, fits in a pocket',   9.99, 200),
    (4, 'Thingamajig','Versatile thingamajig for hobbyists',  19.99,  75),
    (5, 'Gizmo',     'Premium gizmo with extended warranty',  89.99,  20);

-- -----------------------------------------------------------------------
-- Seed data — orders
-- -----------------------------------------------------------------------

INSERT INTO orders (id, customer_id, product, amount) VALUES
    (1, 1, 'Widget',       29.99),
    (2, 1, 'Gadget',       49.99),
    (3, 2, 'Widget',       29.99),
    (4, 4, 'Gizmo',        89.99),
    (5, 4, 'Doohickey',     9.99),
    (6, 5, 'Thingamajig',  19.99);
-- Carol (id=3) has no orders — this is intentional for the bug demo

-- -----------------------------------------------------------------------
-- Seed data — order_items
-- -----------------------------------------------------------------------

INSERT INTO order_items (id, order_id, product_id, qty, unit_price) VALUES
    (1, 1, 1, 1, 29.99),
    (2, 2, 2, 1, 49.99),
    (3, 3, 1, 2, 29.99),
    (4, 4, 5, 1, 89.99),
    (5, 5, 3, 3,  9.99),
    (6, 6, 4, 1, 19.99);

-- -----------------------------------------------------------------------
-- Seed data — reviews
-- -----------------------------------------------------------------------

INSERT INTO reviews (id, customer_id, product_id, rating, comment) VALUES
    (1, 1, 1, 5, 'Love this widget!'),
    (2, 1, 2, 4, 'Gadget works great, minor quirks.'),
    (3, 2, 1, 3, 'It is okay, does the job.'),
    (4, 4, 5, 5, 'Best gizmo I have ever bought.'),
    (5, 4, 3, 2, 'Doohickey broke after a week.'),
    (6, 5, 4, 4, 'Solid thingamajig, would recommend.');
