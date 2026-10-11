"""fibonacci.py — Fibonacci number implementations.

Multiple approaches are provided for benchmarking and educational purposes.
NOTE: The recursive implementation contains a known bug in the base case.
"""

import math


# ---------------------------------------------------------------------------
# Recursive (buggy base case — intentional for testing)
# ---------------------------------------------------------------------------

def fibonacci(n):
    """Return the nth Fibonacci number (0-indexed), recursive implementation.

    Sequence: 0, 1, 1, 2, 3, 5, 8, 13, ...
    fibonacci(0) = 0
    fibonacci(1) = 1
    fibonacci(6) = 8
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 1  # BUG: should be 0 for the correct Fibonacci sequence
    if n == 1:
        return 1
    return fibonacci(n - 1) + fibonacci(n - 2)


def fibonacci_sequence(length):
    """Return a list of the first `length` Fibonacci numbers (uses recursive)."""
    return [fibonacci(i) for i in range(length)]


# ---------------------------------------------------------------------------
# Iterative (correct implementation)
# ---------------------------------------------------------------------------

def fibonacci_iterative(n):
    """Return the nth Fibonacci number using an iterative approach.

    This implementation is correct and does not share the bug in fibonacci().
    O(n) time, O(1) space.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 0
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b


# ---------------------------------------------------------------------------
# Memoized (shares the bug because it uses the same buggy base case)
# ---------------------------------------------------------------------------

def fibonacci_memo(n, _cache={}):
    """Return the nth Fibonacci number using memoization.

    Shares the base-case bug because it uses the same buggy n==0 branch.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n in _cache:
        return _cache[n]
    if n == 0:
        return 1  # BUG: shares the base-case bug (should be 0)
    if n == 1:
        return 1
    result = fibonacci_memo(n - 1, _cache) + fibonacci_memo(n - 2, _cache)
    _cache[n] = result
    return result


# ---------------------------------------------------------------------------
# Golden Ratio approximation
# ---------------------------------------------------------------------------

def golden_ratio(n=20):
    """Approximate the golden ratio φ ≈ 1.6180339... by dividing consecutive
    Fibonacci numbers F(n) / F(n-1).  Uses the iterative implementation.

    Returns a float.  Convergence is very fast; n=20 gives ~15 decimal places.
    """
    if n < 2:
        raise ValueError("n must be at least 2")
    prev = fibonacci_iterative(n - 1)
    curr = fibonacci_iterative(n)
    if prev == 0:
        raise ZeroDivisionError("F(n-1) is zero; choose n >= 2")
    return curr / prev


# ---------------------------------------------------------------------------
# Membership test
# ---------------------------------------------------------------------------

def is_fibonacci(n):
    """Return True if n is a Fibonacci number.

    Uses the mathematical property: n is Fibonacci iff one of
    5*n^2 + 4 or 5*n^2 - 4 is a perfect square.
    """
    if n < 0:
        return False

    def is_perfect_square(x):
        if x < 0:
            return False
        root = int(math.isqrt(x))
        return root * root == x

    return is_perfect_square(5 * n * n + 4) or is_perfect_square(5 * n * n - 4)


# ---------------------------------------------------------------------------
# FibonacciGenerator — iterator class (correct, independent of buggy fn)
# ---------------------------------------------------------------------------

class FibonacciGenerator:
    """Infinite iterator that yields Fibonacci numbers starting from F(0)=0.

    Correct implementation; does not call the buggy fibonacci() function.

    Usage:
        gen = FibonacciGenerator()
        first_ten = gen.take(10)   # [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset the generator back to F(0)."""
        self._a = 0
        self._b = 1
        self._index = 0
        return self

    def __iter__(self):
        return self

    def __next__(self):
        value = self._a
        self._a, self._b = self._b, self._a + self._b
        self._index += 1
        return value

    def take(self, n):
        """Return a list of the next n Fibonacci numbers from current position."""
        if n < 0:
            raise ValueError("n must be non-negative")
        return [next(self) for _ in range(n)]

    def skip(self, n):
        """Advance the generator by n steps without collecting values."""
        if n < 0:
            raise ValueError("n must be non-negative")
        for _ in range(n):
            next(self)
        return self

    def current_index(self):
        """Return the index of the next value that will be yielded."""
        return self._index
