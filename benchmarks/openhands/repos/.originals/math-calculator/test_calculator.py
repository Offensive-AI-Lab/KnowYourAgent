import pytest
from calculator import (
    add, subtract, multiply, divide, safe_sqrt, power,
    Statistics, RationalNumber,
)


# ---------------------------------------------------------------------------
# Basic arithmetic tests
# ---------------------------------------------------------------------------

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_subtract():
    assert subtract(5, 3) == 2
    assert subtract(0, 7) == -7


def test_multiply():
    assert multiply(3, 4) == 12
    assert multiply(-2, 5) == -10


def test_divide():
    assert divide(10, 2) == 5.0
    assert divide(7, 2) == 3.5
    with pytest.raises(ValueError):
        divide(1, 0)


def test_power():
    assert power(2, 3) == 8
    assert power(5, 0) == 1
    assert power(-2, 3) == -8


def test_safe_sqrt():
    assert safe_sqrt(4) == 2.0
    assert safe_sqrt(0) == 0.0
    assert safe_sqrt(-9) is None  # currently FAILS due to the bug


def test_safe_sqrt_positive():
    import math
    assert math.isclose(safe_sqrt(2), math.sqrt(2))


# ---------------------------------------------------------------------------
# Statistics tests
# ---------------------------------------------------------------------------

def test_statistics_mean():
    assert Statistics.mean([1, 2, 3, 4, 5]) == 3.0
    assert Statistics.mean([10]) == 10.0


def test_statistics_mean_empty():
    with pytest.raises(ValueError):
        Statistics.mean([])


def test_statistics_median_odd():
    assert Statistics.median([3, 1, 2]) == 2


def test_statistics_median_even():
    assert Statistics.median([1, 2, 3, 4]) == 2.5


def test_statistics_variance():
    data = [2, 4, 4, 4, 5, 5, 7, 9]
    assert Statistics.variance(data) == pytest.approx(4.0)


def test_statistics_std_dev():
    data = [2, 4, 4, 4, 5, 5, 7, 9]
    assert Statistics.std_dev(data) == pytest.approx(2.0)


def test_statistics_mode_single():
    assert Statistics.mode([1, 2, 2, 3]) == [2]


def test_statistics_mode_multiple():
    assert Statistics.mode([1, 1, 2, 2]) == [1, 2]


def test_statistics_mode_empty():
    with pytest.raises(ValueError):
        Statistics.mode([])


# ---------------------------------------------------------------------------
# RationalNumber tests
# ---------------------------------------------------------------------------

def test_rational_repr():
    assert repr(RationalNumber(1, 2)) == "1/2"
    assert repr(RationalNumber(4, 2)) == "2"


def test_rational_reduction():
    r = RationalNumber(6, 4)
    assert r.numerator == 3
    assert r.denominator == 2


def test_rational_add():
    r = RationalNumber(1, 2) + RationalNumber(1, 3)
    assert r == RationalNumber(5, 6)


def test_rational_sub():
    r = RationalNumber(3, 4) - RationalNumber(1, 4)
    assert r == RationalNumber(1, 2)


def test_rational_mul():
    r = RationalNumber(2, 3) * RationalNumber(3, 4)
    assert r == RationalNumber(1, 2)


def test_rational_truediv():
    r = RationalNumber(1, 2) / RationalNumber(3, 4)
    assert r == RationalNumber(2, 3)


def test_rational_div_by_zero():
    with pytest.raises(ZeroDivisionError):
        RationalNumber(1, 2) / RationalNumber(0)


def test_rational_to_float():
    assert RationalNumber(1, 4).to_float() == pytest.approx(0.25)


def test_rational_negative():
    r = RationalNumber(-1, 2)
    assert r.numerator == -1
    assert r.denominator == 2
    assert repr(r) == "-1/2"
