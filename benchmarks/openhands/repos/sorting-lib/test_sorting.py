from sorting import (
    bubble_sort, insertion_sort, selection_sort,
    merge_sort, quick_sort, heap_sort,
    is_sorted, benchmark,
)


# ---------------------------------------------------------------------------
# Bubble sort (contains the bug: sorts descending instead of ascending)
# ---------------------------------------------------------------------------

def test_bubble_sort_ascending():
    # This test FAILS because bubble_sort has the wrong comparison operator
    assert bubble_sort([3, 1, 4, 1, 5, 9, 2, 6]) == [1, 1, 2, 3, 4, 5, 6, 9]


def test_bubble_sort_already_sorted():
    assert bubble_sort([1, 2, 3]) == [1, 2, 3]


def test_bubble_sort_empty():
    assert bubble_sort([]) == []


def test_bubble_sort_single():
    assert bubble_sort([42]) == [42]


# ---------------------------------------------------------------------------
# Insertion sort
# ---------------------------------------------------------------------------

def test_insertion_sort_basic():
    assert insertion_sort([5, 2, 8, 1]) == [1, 2, 5, 8]


def test_insertion_sort_duplicates():
    assert insertion_sort([3, 3, 1, 2]) == [1, 2, 3, 3]


def test_insertion_sort_empty():
    assert insertion_sort([]) == []


# ---------------------------------------------------------------------------
# Selection sort
# ---------------------------------------------------------------------------

def test_selection_sort_basic():
    assert selection_sort([64, 25, 12, 22, 11]) == [11, 12, 22, 25, 64]


def test_selection_sort_single():
    assert selection_sort([7]) == [7]


# ---------------------------------------------------------------------------
# Merge sort
# ---------------------------------------------------------------------------

def test_merge_sort_basic():
    assert merge_sort([38, 27, 43, 3, 9, 82, 10]) == [3, 9, 10, 27, 38, 43, 82]


def test_merge_sort_empty():
    assert merge_sort([]) == []


def test_merge_sort_negative():
    assert merge_sort([-5, 3, -1, 0]) == [-5, -1, 0, 3]


def test_merge_sort_already_sorted():
    data = list(range(10))
    assert merge_sort(data) == data


# ---------------------------------------------------------------------------
# Quick sort
# ---------------------------------------------------------------------------

def test_quick_sort_basic():
    assert quick_sort([10, 7, 8, 9, 1, 5]) == [1, 5, 7, 8, 9, 10]


def test_quick_sort_empty():
    assert quick_sort([]) == []


def test_quick_sort_negative():
    assert quick_sort([-3, 1, -1, 0, 2]) == [-3, -1, 0, 1, 2]


# ---------------------------------------------------------------------------
# Heap sort
# ---------------------------------------------------------------------------

def test_heap_sort_basic():
    assert heap_sort([12, 11, 13, 5, 6, 7]) == [5, 6, 7, 11, 12, 13]


def test_heap_sort_empty():
    assert heap_sort([]) == []


def test_heap_sort_duplicates():
    assert heap_sort([4, 4, 2, 2, 1]) == [1, 2, 2, 4, 4]


# ---------------------------------------------------------------------------
# is_sorted helper
# ---------------------------------------------------------------------------

def test_is_sorted_true():
    assert is_sorted([1, 2, 3, 4]) is True


def test_is_sorted_false():
    assert is_sorted([1, 3, 2]) is False


def test_is_sorted_reverse():
    assert is_sorted([4, 3, 2, 1], reverse=True) is True


def test_is_sorted_single():
    assert is_sorted([99]) is True


def test_is_sorted_empty():
    assert is_sorted([]) is True


# ---------------------------------------------------------------------------
# benchmark helper
# ---------------------------------------------------------------------------

def test_benchmark_returns_keys():
    result = benchmark([5, 3, 1, 4, 2], merge_sort, runs=3)
    assert "min" in result and "max" in result and "avg" in result
    assert result["runs"] == 3
    assert result["min"] <= result["avg"] <= result["max"]
