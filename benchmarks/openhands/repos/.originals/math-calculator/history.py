"""
history.py — Persistent calculation history with CSV export and summary stats.
"""

import csv
import statistics
from datetime import datetime


class CalculationHistory:
    """Records calculator operations and provides basic analytics."""

    def __init__(self):
        self._records = []  # list of (timestamp, expression_str, result)

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def record(self, expr, result):
        """Append a new (expression, result) entry to the history.

        Args:
            expr:   Human-readable expression string, e.g. "sqrt(9)".
            result: The numeric result of the expression.
        """
        timestamp = datetime.utcnow().isoformat(timespec="seconds")
        self._records.append((timestamp, expr, result))

    def clear(self):
        """Remove all entries from the history."""
        self._records.clear()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def last(self, n=10):
        """Return the most recent n entries as a list of (expr, result) tuples."""
        return [(expr, result) for _, expr, result in self._records[-n:]]

    def all_records(self):
        """Return every entry as (timestamp, expr, result) tuples."""
        return list(self._records)

    def __len__(self):
        return len(self._records)

    def __bool__(self):
        return bool(self._records)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def summary_stats(self):
        """Return a dict with aggregate statistics over recorded results.

        Returns:
            dict with keys: count, mean_result, min_result, max_result,
            std_dev_result (or None if fewer than 2 entries).
        """
        if not self._records:
            return {
                "count": 0,
                "mean_result": None,
                "min_result": None,
                "max_result": None,
                "std_dev_result": None,
            }

        numeric = [r for _, _, r in self._records if isinstance(r, (int, float))]
        if not numeric:
            return {
                "count": len(self._records),
                "mean_result": None,
                "min_result": None,
                "max_result": None,
                "std_dev_result": None,
            }

        return {
            "count": len(self._records),
            "mean_result": statistics.mean(numeric),
            "min_result": min(numeric),
            "max_result": max(numeric),
            "std_dev_result": statistics.pstdev(numeric) if len(numeric) >= 2 else None,
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_csv(self, filepath):
        """Write the full history to a CSV file.

        The CSV has three columns: timestamp, expression, result.

        Args:
            filepath: Path (str or Path-like) for the output CSV.

        Returns:
            The number of rows written (not counting the header).
        """
        with open(filepath, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["timestamp", "expression", "result"])
            for timestamp, expr, result in self._records:
                writer.writerow([timestamp, expr, result])
        return len(self._records)
