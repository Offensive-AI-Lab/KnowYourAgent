import sqlite3

from queries import get_low_stock_products

def test_paginate_allowlist():
    import pytest
    from queries import paginate, setup_db
    conn = sqlite3.connect(":memory:")
    setup_db(conn)
    # Allowed table: should work
    rows = paginate(conn, "customers", 1, 2)
    assert isinstance(rows, list)
    # Disallowed table: should raise ValueError
    with pytest.raises(ValueError):
        paginate(conn, "not_a_table")
    with pytest.raises(ValueError):
        paginate(conn, "users;")
    print("PASS: paginate allowlist")

from queries import get_customers_with_orders, setup_db

def test_customers_with_no_orders():
    conn = sqlite3.connect(":memory:")
    setup_db(conn)
    customers = get_customers_with_orders(conn)
    # Make a mapping from customer name to total_spent
    # Try both: sqlite3.Row and tuple
    try:
        result = {row['name']: row['total_spent'] for row in customers}
        print(f"Customer totals: {result}")
        assert 'Carol' in result, f"Carol missing from customers: {result}" 
        assert result['Carol'] == 0, f"Carol total is not 0: {result['Carol']}"
        # Also check Alice (should have positive total, e.g. 79.98)
        assert 'Alice' in result, f"Alice missing from customers: {result}"
        assert abs(result['Alice'] - 79.98) < 1e-6, f"Alice total is {result['Alice']} (expected 79.98)"

    except (TypeError, KeyError, IndexError):
        # Assume tuple: inspect by column index
        print(f"Raw customers tuple result: {customers}")
        assert any(row[1] == 'Carol' and row[3] == 0 for row in customers), 'Carol with total_spent=0 missing in tuple result'
        assert any(row[1] == 'Alice' and abs(row[3] - 79.98) < 1e-6 for row in customers), 'Alice with correct total_spent missing in tuple result'


def test_get_low_stock_products():
    conn = sqlite3.connect(":memory:")
    setup_db(conn)
    conn.execute("DELETE FROM products")

    # Insert some products
    products = [
        (1, "Pencil", 100),
        (2, "Eraser", 3),
        (3, "Ruler", 0),
        (4, "Pen", 8),
        (5, "Marker", 5),
        (6, "Stapler", 1)
    ]
    for pid, name, stock in products:
        conn.execute("INSERT INTO products (id, name, price, stock) VALUES (?, ?, 1.0, ?)", (pid, name, stock))
    conn.commit()
    low = get_low_stock_products(conn, threshold=5)
    # Should include Eraser (3), Ruler (0), Stapler (1) and sorted by stock asc
    result = [(row[1], row[2]) for row in low]
    assert result == [("Ruler", 0), ("Stapler", 1), ("Eraser", 3)], f"Got: {result}"
    print("PASS: Low stock products:", result)
    # Test default threshold (should be 5)
    low_default = get_low_stock_products(conn)
    result_default = [(row[1], row[2]) for row in low_default]
    assert result_default == [("Ruler", 0), ("Stapler", 1), ("Eraser", 3)], f"Default threshold failed: {result_default}"
    print("PASS: Low stock products (default threshold):", result_default)



if __name__ == "__main__":
    test_customers_with_no_orders()
    test_get_low_stock_products()
