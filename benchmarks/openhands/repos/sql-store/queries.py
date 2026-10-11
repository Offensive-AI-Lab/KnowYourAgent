"""
queries.py — SQL query functions for the sql-store application.
"""

import sqlite3


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_connection(db_path: str = ":memory:") -> sqlite3.Connection:
    """Open and return a SQLite connection with Row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def setup_db(conn: sqlite3.Connection) -> None:
    """Execute schema.sql against the given connection."""
    with open("schema.sql") as f:
        conn.executescript(f.read())


# ---------------------------------------------------------------------------
# Customer queries
# ---------------------------------------------------------------------------

def get_customers_with_orders(conn: sqlite3.Connection):
    """Return all customers along with their total order amount.

    Customers with no orders should appear with a total of 0.
    """
    query = """
        SELECT c.id, c.name, c.email,
               COALESCE(SUM(o.amount), 0) AS total_spent
        FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.id
        GROUP BY c.id
        ORDER BY c.name
    """
    # BUG: INNER JOIN excludes customers who have no orders.
    # Should be LEFT JOIN so Carol (who has no orders) is included.
    return conn.execute(query).fetchall()


def get_customer_ltv(conn: sqlite3.Connection, customer_id: int):
    """Return the lifetime value (total amount spent) for a single customer.

    Args:
        conn:        An open SQLite connection.
        customer_id: The customer's primary-key id.

    Returns:
        A sqlite3.Row with columns (id, name, email, total_spent), or None
        if no customer with that id exists.
    """
    query = """
        SELECT c.id, c.name, c.email,
               COALESCE(SUM(o.amount), 0) AS total_spent
        FROM customers c
        LEFT JOIN orders o ON o.customer_id = c.id
        WHERE c.id = ?
        GROUP BY c.id
    """
    return conn.execute(query, (customer_id,)).fetchone()


def upsert_customer(conn: sqlite3.Connection, name: str, email: str) -> int:
    """Insert a customer or replace the existing row if the email matches.

    Args:
        conn:  An open SQLite connection.
        name:  The customer's full name.
        email: The customer's unique email address.

    Returns:
        The rowid of the inserted or replaced row.
    """
    cursor = conn.execute(
        "INSERT OR REPLACE INTO customers (name, email) VALUES (?, ?)",
        (name, email),
    )
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Product queries
# ---------------------------------------------------------------------------

def get_product_revenue(conn: sqlite3.Connection):
    """Return each product's name and total revenue from order_items.

    Returns:
        List of sqlite3.Row with columns (name, total_revenue).
    """
    query = """
        SELECT p.name,
               COALESCE(SUM(oi.qty * oi.unit_price), 0) AS total_revenue
        FROM products p
        LEFT JOIN order_items oi ON oi.product_id = p.id
        GROUP BY p.id
        ORDER BY total_revenue DESC
    """
    return conn.execute(query).fetchall()


def get_unreviewed_products(conn: sqlite3.Connection):
    """Return products that have received no reviews.

    Returns:
        List of sqlite3.Row with columns (id, name, price).
    """
    query = """
        SELECT p.id, p.name, p.price
        FROM products p
        LEFT JOIN reviews r ON r.product_id = p.id
        WHERE r.id IS NULL
        ORDER BY p.name
    """
    return conn.execute(query).fetchall()


def search_products(conn: sqlite3.Connection, query: str):
    """Full-text LIKE search across product name and description.

    Args:
        conn:  An open SQLite connection.
        query: The search term (case-insensitive).

    Returns:
        List of sqlite3.Row matching the search term.
    """
    pattern = f"%{query}%"
    sql = """
        SELECT id, name, description, price, stock
        FROM products
        WHERE name LIKE ? OR description LIKE ?
        ORDER BY name
    """
    return conn.execute(sql, (pattern, pattern)).fetchall()


def get_low_stock_products(conn: sqlite3.Connection, threshold: int = 5):
    """Return products whose stock is below a given threshold.

    Args:
        conn:      An open SQLite connection.
        threshold: Stock threshold. Products with stock < threshold are returned.

    Returns:
        List of sqlite3.Row with columns (id, name, stock), ordered by stock ascending.
    """
    query = """
        SELECT id, name, stock
        FROM products
        WHERE stock < ?
        ORDER BY stock ASC
    """
    return conn.execute(query, (threshold,)).fetchall()

# ---------------------------------------------------------------------------
# Review queries
# ---------------------------------------------------------------------------

def get_top_reviewers(conn: sqlite3.Connection, min_reviews: int = 2):
    """Return customers who have written at least min_reviews reviews.

    Args:
        conn:        An open SQLite connection.
        min_reviews: Minimum number of reviews required (default 2).

    Returns:
        List of sqlite3.Row with columns (id, name, email, review_count).
    """
    query = """
        SELECT c.id, c.name, c.email, COUNT(r.id) AS review_count
        FROM customers c
        INNER JOIN reviews r ON r.customer_id = c.id
        GROUP BY c.id
        HAVING review_count >= ?
        ORDER BY review_count DESC
    """
    return conn.execute(query, (min_reviews,)).fetchall()


# ---------------------------------------------------------------------------
# Legacy / utility queries
# ---------------------------------------------------------------------------

def get_top_products(conn: sqlite3.Connection, limit: int = 5):
    """Return top products by revenue (from the orders table).

    Args:
        conn:  An open SQLite connection.
        limit: Maximum number of products to return.

    Returns:
        List of sqlite3.Row with columns (product, order_count, revenue).
    """
    query = """
        SELECT product, COUNT(*) AS order_count, SUM(amount) AS revenue
        FROM orders
        GROUP BY product
        ORDER BY revenue DESC
        LIMIT ?
    """
    return conn.execute(query, (limit,)).fetchall()


def paginate(conn: sqlite3.Connection, table: str, page: int = 1, page_size: int = 20):
    """Return a page of rows from any table.

    Args:
        conn:      An open SQLite connection.
        table:     The name of the table to paginate.
        page:      1-indexed page number.
        page_size: Number of rows per page.

    Returns:
        List of sqlite3.Row for the requested page.

    Warning:
        The table name is interpolated directly — do not pass user-supplied
        values to this function without allowlist validation.
    """
    ALLOWED_TABLES = {"customers", "orders", "products", "order_items", "reviews"}
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Table '{table}' is not allowed.")
    offset = (max(1, page) - 1) * page_size
    query  = f"SELECT * FROM {table} LIMIT ? OFFSET ?"  # nosec
    return conn.execute(query, (page_size, offset)).fetchall()
