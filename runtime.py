"""State the app shares across all browser sessions: the answer cache and today's spending.

Both live in the server's memory (the app keeps one of each with st.cache_resource), so they are
emptied when the app restarts. Plain Python, so the tests can use them without Streamlit.
"""

import copy
import os
import threading
from collections import OrderedDict
from datetime import date


class AnswerCache:
    """Answers by key, newest kept when full. Returns copies so a shown answer can't change a cached one."""

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key) -> dict | None:
        with self._lock:
            if key not in self._items:
                return None
            self._items.move_to_end(key)
            return copy.deepcopy(self._items[key])

    def put(self, key, result: dict) -> None:
        with self._lock:
            self._items[key] = copy.deepcopy(result)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


class DailyBudget:
    """Money spent on model calls today by everyone using this app process; resets each day."""

    def __init__(self):
        self._day = date.today()
        self._spent = 0.0
        self._lock = threading.Lock()

    def _roll_over(self) -> None:
        if date.today() != self._day:
            self._day, self._spent = date.today(), 0.0

    def add(self, cost_usd: float | None) -> None:
        with self._lock:
            self._roll_over()
            self._spent += cost_usd or 0.0

    def spent(self) -> float:
        with self._lock:
            self._roll_over()
            return self._spent


def max_calls_per_session() -> int | None:
    value = os.getenv("MAX_CALLS_PER_SESSION", "").strip()
    return int(value) if value else None


def daily_budget_usd() -> float | None:
    value = os.getenv("DAILY_BUDGET_USD", "").strip()
    return float(value) if value else None


def limit_reason(session_calls: int, new_calls: int, spent_today: float) -> str | None:
    """Why new_calls more model calls are not allowed now, or None if they are."""
    max_calls = max_calls_per_session()
    if max_calls is not None and session_calls + new_calls > max_calls:
        return f"This session has reached its limit of {max_calls} model calls."
    budget = daily_budget_usd()
    if budget is not None and spent_today >= budget:
        return f"Today's model budget (${budget:.2f}) has been used. Please try again tomorrow."
    return None


def flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in ("1", "true", "yes", "on") if value else default
