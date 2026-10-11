"""
calculator.py — Core arithmetic, statistics, and rational number utilities.
"""

import math
from collections import Counter


# ---------------------------------------------------------------------------
# Basic arithmetic
# ---------------------------------------------------------------------------

def add(a, b):
    """Return the sum of a and b."""
    return a + b


def subtract(a, b):
    """Return the difference of a and b."""
    return a - b


def multiply(a, b):
    """Return the product of a and b."""
    return a * b


def divide(a, b):
    """Return the quotient of a and b. Raises ValueError on division by zero."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def power(base, exp):
    """Return base raised to the power of exp."""
    return base ** exp


def safe_sqrt(x):
    """Return the square root of x, or None if x is negative."""
    if x < 0:
        return None
    return math.sqrt(x)

