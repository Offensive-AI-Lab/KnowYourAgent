"""
reports.py — High-level report generation on top of the sql-store data.
"""

import json
import sqlite3
from datetime import datetime, timedelta


class ReportGenerator:
    """Generates analytical reports from the sql-store database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------------
    # Revenue reports
    # ------------------------------------------------------------------

    def monthly_revenue(self, year: int) -> dict:
        """Return a month → total_revenue mapping for the given calendar year.

        Args:
            year: Four-digit calendar year (e.g. 2024).

        Returns:
            A dict with integer keys 1–12. Months with no sales have value 0.0.
        """
        query = """
            SELECT CAST(strftime('%m', created_at) AS INTEGER) AS month,
                   SUM(amount) AS revenue
            FROM orders
            WHERE strftime('%Y', created_at) = ?
            GROUP BY month
        """
        rows = self.conn.execute(query, (str(year),)).fetchall()
        monthly = {m: 0.0 for m in range(1, 13)}
        for row in rows:
            monthly[row["month"]] = row["revenue"]
        return monthly

    # ------------------------------------------------------------------
    # Customer segmentation
    # ------------------------------------------------------------------

    def customer_segments(self) -> dict:
        """Classify customers into VIP / regular / inactive segments.

        Segmentation rules:
            VIP      — total lifetime spend > 100
            inactive — no orders placed in the last 90 days
            regular  — everyone else

        Returns:
            A dict with keys 'vip', 'regular', 'inactive', each mapping
            to a list of customer ids (integers).
        """
        cutoff = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

        query = """
            SELECT c.id,
                   COALESCE(SUM(o.amount), 0)          AS total_spent,
                   MAX(o.created_at)                   AS last_order_at
            FROM customers c
            LEFT JOIN orders o ON o.customer_id = c.id
            GROUP BY c.id
        """
        rows = self.conn.execute(query).fetchall()

        vip      = []
        inactive = []
        regular  = []

        for row in rows:
            cid         = row["id"]
            total_spent = row["total_spent"]
            last_order  = row["last_order_at"]

            if total_spent > 100:
                vip.append(cid)
            elif last_order is None or last_order[:10] < cutoff:
                inactive.append(cid)
            else:
                regular.append(cid)

        return {"vip": vip, "regular": regular, "inactive": inactive}

    # ------------------------------------------------------------------
    # Export utilities
    # ------------------------------------------------------------------

    @staticmethod
    def export_to_json(data, filepath: str) -> int:
        """Serialise data to a JSON file.

        Args:
            data:     Any JSON-serialisable object.
            filepath: Destination file path.

        Returns:
            The number of bytes written.
        """
        text = json.dumps(data, indent=2, default=str)
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(text)
        return len(text.encode("utf-8"))

    # ------------------------------------------------------------------
    # Convenience / summary helpers
    # ------------------------------------------------------------------

    def product_rating_summary(self) -> dict:
        """Return average rating and review count per product.

        Returns:
            A dict mapping product name to {'avg_rating': float, 'review_count': int}.
        """
        query = """
            SELECT p.name,
                   AVG(r.rating)  AS avg_rating,
                   COUNT(r.id)    AS review_count
            FROM products p
            LEFT JOIN reviews r ON r.product_id = p.id
            GROUP BY p.id
            ORDER BY p.name
        """
        rows = self.conn.execute(query).fetchall()
        return {
            row["name"]: {
                "avg_rating":   round(row["avg_rating"], 2) if row["avg_rating"] else None,
                "review_count": row["review_count"],
            }
            for row in rows
        }

    def overall_summary(self) -> dict:
        """Return a top-level dashboard summary dict."""
        totals = self.conn.execute("""
            SELECT COUNT(DISTINCT c.id)  AS customer_count,
                   COUNT(DISTINCT o.id)  AS order_count,
                   COALESCE(SUM(o.amount), 0) AS total_revenue
            FROM customers c
            LEFT JOIN orders o ON o.customer_id = c.id
        """).fetchone()

        return {
            "customer_count": totals["customer_count"],
            "order_count":    totals["order_count"],
            "total_revenue":  round(totals["total_revenue"], 2),
            "generated_at":   datetime.utcnow().isoformat(timespec="seconds"),
        }
