"""A shared budget for the LLM calls visitors can trigger.

Two pages spend the provider's quota on a click — Ask the Data and the My Fit
deep-dive — and the app is public. The free tier it runs on is counted in
requests per day and is the same pool the daily enrichment draws from, so
without a ceiling one visitor holding a button down (or one script) empties it
for everyone, the pipeline included.

Two limits, deliberately small and both stated in the UI:

* a **per-visitor** allowance, so one session cannot take the whole day's pool;
* an **app-wide** rolling 24-hour allowance, which is the one that protects the
  quota.

The counter lives in the server process. A restart resets it, and two replicas
would each count their own — acceptable for a single free-tier container, where
this is a courtesy limit backed by the provider's own hard one.

:class:`CallBudget` is Streamlit-free so it can be unit-tested with a fake
clock; the functions below bind it to the running app.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

import streamlit as st

from jmi_core.settings import get_settings

WINDOW_S = 24 * 60 * 60
#: LLM calls one browser session may make. Enough to try the feature properly.
PER_SESSION = 5
_SESSION_KEY = "_llm_calls_used"


class CallBudget:
    """At most ``max_calls`` in any rolling ``window_s`` seconds. Thread-safe."""

    def __init__(
        self,
        max_calls: int,
        window_s: float = WINDOW_S,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._clock = clock
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def _expire(self) -> None:
        horizon = self._clock() - self.window_s
        while self._stamps and self._stamps[0] <= horizon:
            self._stamps.popleft()

    def remaining(self) -> int:
        with self._lock:
            self._expire()
            return max(self.max_calls - len(self._stamps), 0)

    def try_spend(self) -> bool:
        """Take one call if any is left. False means the budget is spent."""
        with self._lock:
            self._expire()
            if len(self._stamps) >= self.max_calls:
                return False
            self._stamps.append(self._clock())
            return True


@st.cache_resource
def _app_budget() -> CallBudget:
    return CallBudget(get_settings().app_llm_calls_per_day)


def llm_calls_left() -> int:
    """How many LLM calls this visitor can still make right now."""
    used = int(st.session_state.get(_SESSION_KEY, 0))
    return max(min(PER_SESSION - used, _app_budget().remaining()), 0)


def spend_llm_call() -> bool:
    """Reserve one LLM call for this visitor. Call it *before* the request."""
    used = int(st.session_state.get(_SESSION_KEY, 0))
    if used >= PER_SESSION or not _app_budget().try_spend():
        return False
    st.session_state[_SESSION_KEY] = used + 1
    return True


def budget_caption() -> str:
    """One line for the UI: what is left, or why nothing is."""
    left = llm_calls_left()
    if left:
        return f"{left} LLM call{'s' if left != 1 else ''} left for you today."
    if int(st.session_state.get(_SESSION_KEY, 0)) >= PER_SESSION:
        return f"You have used this session's {PER_SESSION} LLM calls."
    return (
        "Today's shared LLM budget is spent — the app runs on a free tier. "
        "Everything that is not an LLM call still works."
    )
