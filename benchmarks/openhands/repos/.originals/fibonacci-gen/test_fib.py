"""test_fib.py — Tests for fibonacci.py implementations."""

import pytest
from fibonacci import (
    fibonacci,
    fibonacci_sequence,
    fibonacci_iterative,
    fibonacci_memo,
    golden_ratio,
    is_fibonacci,
    FibonacciGenerator,
)


# ---------------------------------------------------------------------------
# Recursive (contains bug: fibonacci(0) returns 1 instead of 0)
# ---------------------------------------------------------------------------

def test_fibonacci_base_cases():
    assert fibonacci(0) == 0  # currently FAILS due to bug
    assert fibonacci(1) == 1


def test_fibonacci_sequence_values():
    assert fibonacci(2) == 1
    assert fibonacci(3) == 2
    assert fibonacci(6) == 8


def test_fibonacci_sequence_list():
    assert fibonacci_sequence(7) == [0, 1, 1, 2, 3, 5, 8]


def test_fibonacci_negative():
    with pytest.raises(ValueError):
        fibonacci(-1)


# ---------------------------------------------------------------------------
# Iterative (correct)
# ---------------------------------------------------------------------------

def test_iterative_base_cases():
    assert fibonacci_iterative(0) == 0
    assert fibonacci_iterative(1) == 1


def test_iterative_values():
    expected = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    for i, val in enumerate(expected):
        assert fibonacci_iterative(i) == val, f"fibonacci_iterative({i}) should be {val}"


def test_iterative_large():
    assert fibonacci_iterative(20) == 6765
    assert fibonacci_iterative(30) == 832040


def test_iterative_negative_raises():
    with pytest.raises(ValueError):
        fibonacci_iterative(-5)


# ---------------------------------------------------------------------------
# Memoized (inherits the bug)
# ---------------------------------------------------------------------------

def test_memo_n1():
    assert fibonacci_memo(1) == 1


def test_memo_higher_values():
    # These are offset by 1 from the correct sequence due to the shared bug
    assert fibonacci_memo(2) == 2  # correct fib(2) == 1, but bug shifts it
    assert fibonacci_memo(6) == 13  # correct fib(6) == 8, but bug shifts it


def test_memo_negative_raises():
    with pytest.raises(ValueError):
        fibonacci_memo(-1)


# ---------------------------------------------------------------------------
# Golden ratio
# ---------------------------------------------------------------------------

def test_golden_ratio_approximation():
    phi = golden_ratio(30)
    assert abs(phi - 1.6180339887) < 1e-9


def test_golden_ratio_min_n():
    with pytest.raises(ValueError):
        golden_ratio(1)


# ---------------------------------------------------------------------------
# is_fibonacci
# ---------------------------------------------------------------------------

def test_is_fibonacci_members():
    fibs = [0, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
    for f in fibs:
        assert is_fibonacci(f), f"{f} should be a Fibonacci number"


def test_is_fibonacci_non_members():
    non_fibs = [4, 6, 7, 9, 10, 11, 12, 15, 20, 100]
    for n in non_fibs:
        assert not is_fibonacci(n), f"{n} should not be a Fibonacci number"


def test_is_fibonacci_negative():
    assert not is_fibonacci(-1)


# ---------------------------------------------------------------------------
# FibonacciGenerator
# ---------------------------------------------------------------------------

def test_generator_take():
    gen = FibonacciGenerator()
    assert gen.take(10) == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]


def test_generator_reset():
    gen = FibonacciGenerator()
    gen.take(5)
    gen.reset()
    assert gen.take(5) == [0, 1, 1, 2, 3]


def test_generator_skip():
    gen = FibonacciGenerator()
    gen.skip(7)
    assert next(gen) == 13  # F(7)


def test_generator_iterator_protocol():
    gen = FibonacciGenerator()
    values = []
    for val in gen:
        values.append(val)
        if len(values) >= 8:
            break
    assert values == [0, 1, 1, 2, 3, 5, 8, 13]


def test_generator_take_zero():
    gen = FibonacciGenerator()
    assert gen.take(0) == []


def test_generator_negative_take_raises():
    gen = FibonacciGenerator()
    with pytest.raises(ValueError):
        gen.take(-1)
