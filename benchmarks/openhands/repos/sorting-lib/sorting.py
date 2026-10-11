"""
sorting.py — A collection of sorting algorithms with benchmarking utilities.
"""

import time
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_sorted(arr: list, reverse: bool = False) -> bool:
    """Return True if arr is sorted in ascending order (or descending if reverse=True)."""
    if len(arr) <= 1:
        return True
    pairs = zip(arr, arr[1:])
    if reverse:
        return all(a >= b for a, b in pairs)
    return all(a <= b for a, b in pairs)


def benchmark(arr: list, func, runs: int = 5) -> dict:
    """Time a sort function over multiple runs and return aggregate statistics.

    Args:
        arr:   The input list to sort (a fresh copy is made each run).
        func:  A callable that accepts a list and returns a sorted list.
        runs:  Number of timed repetitions.

    Returns:
        A dict with keys: 'min', 'max', 'avg', 'runs', 'function'.
    """
    times = []
    for _ in range(runs):
        data = arr.copy()
        t0 = time.perf_counter()
        func(data)
        times.append(time.perf_counter() - t0)

    return {
        "function": func.__name__,
        "runs":     runs,
        "min":      min(times),
        "max":      max(times),
        "avg":      sum(times) / len(times),
    }


# ---------------------------------------------------------------------------
# O(n²) algorithms
# ---------------------------------------------------------------------------

def bubble_sort(arr: list) -> list:
    """Sort a list in ascending order using bubble sort."""
    n = len(arr)
    arr = arr.copy()
    for i in range(n):
        for j in range(n - i - 1):
            if arr[j] > arr[j + 1]:  # Fixed: correct to sort ascending
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr


def insertion_sort(arr: list) -> list:
    """Sort a list in ascending order using insertion sort."""
    arr = arr.copy()
    for i in range(1, len(arr)):
        key = arr[i]
        j = i - 1
        while j >= 0 and arr[j] > key:
            arr[j + 1] = arr[j]
            j -= 1
        arr[j + 1] = key
    return arr


def selection_sort(arr: list) -> list:
    """Sort a list in ascending order using selection sort."""
    arr = arr.copy()
    n = len(arr)
    for i in range(n):
        min_idx = i
        for j in range(i + 1, n):
            if arr[j] < arr[min_idx]:
                min_idx = j
        arr[i], arr[min_idx] = arr[min_idx], arr[i]
    return arr


# ---------------------------------------------------------------------------
# O(n log n) algorithms
# ---------------------------------------------------------------------------

def merge_sort(arr: list) -> list:
    """Sort a list in ascending order using recursive merge sort."""
    if len(arr) <= 1:
        return list(arr)

    mid   = len(arr) // 2
    left  = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])

    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result


def quick_sort(arr: list, lo: int = 0, hi: Optional[int] = None) -> list:
    """Sort a list in-place using Lomuto partition quicksort.

    Returns the sorted list (operates on a copy when called at the top level).
    """
    if lo == 0 and hi is None:
        arr = arr.copy()
        hi = len(arr) - 1

    if lo < hi:
        pivot_idx = _lomuto_partition(arr, lo, hi)
        quick_sort(arr, lo, pivot_idx - 1)
        quick_sort(arr, pivot_idx + 1, hi)

    return arr


def _lomuto_partition(arr: list, lo: int, hi: int) -> int:
    pivot = arr[hi]
    i = lo - 1
    for j in range(lo, hi):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[hi] = arr[hi], arr[i + 1]
    return i + 1


def heap_sort(arr: list) -> list:
    """Sort a list in ascending order using heap sort."""
    arr = arr.copy()
    n = len(arr)

    # Build max-heap
    for i in range(n // 2 - 1, -1, -1):
        _sift_down(arr, n, i)

    # Extract elements one by one
    for end in range(n - 1, 0, -1):
        arr[0], arr[end] = arr[end], arr[0]
        _sift_down(arr, end, 0)

    return arr


def _sift_down(arr: list, n: int, root: int) -> None:
    largest = root
    left    = 2 * root + 1
    right   = 2 * root + 2

    if left < n and arr[left] > arr[largest]:
        largest = left
    if right < n and arr[right] > arr[largest]:
        largest = right

    if largest != root:
        arr[root], arr[largest] = arr[largest], arr[root]
        _sift_down(arr, n, largest)
