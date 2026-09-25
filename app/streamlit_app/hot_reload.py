"""Drop the repo's modules that went stale under a running server.

Streamlit Community Cloud redeploys a push by pulling the new commit into the
running container. Page scripts are re-executed on every run, so they are always
the new code — but everything they import (``streamlit_app.ui``, ``jmi_core``,
``jmi_enrichment``...) stays in ``sys.modules`` as first imported. A page that
asks a new question of an old helper then fails on the live app until someone
reboots it: the sibling spanish-housing-radar app died twice this way, once on
an ImportError and once on an ``UnserializableReturnValueError``.

``Home.py`` runs on every rerun, so it reloads this module and calls
``drop_stale()`` before anything imports a helper. Two rules, both learned the
hard way over there:

* **Drop every module, not only the changed ones.** An unchanged module can
  hold objects from a changed one; keeping it left a page calling a dropped
  module's function, whose return value no longer pickled for ``st.cache_data``.
* **A module never seen before is judged against the process start.** One
  imported after a drop has no recorded mtime until the next run looks at it;
  a pull landing in between used to become the baseline and go unnoticed.

Every workspace member lives in the repo (``app/``, ``libs/``, ``enrichment/``,
``scrapers/``...), so the whole repo is watched; ``.venv`` is not. The cost is
a re-import of the app's own modules, once per deploy.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Kept on ``sys``, which outlives every script run, because this module's own
# globals are replaced whenever it is reloaded.
_STATE_ATTR = "_jmi_module_mtimes_v1"
_STARTED = "__started__"


def _repo_modules(root: Path) -> dict[str, Path]:
    prefix = str(root.resolve())
    found = {}
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if name == "__main__" or not file:
            continue
        path = Path(file).resolve()
        if (
            str(path).startswith(prefix)
            and ".venv" not in path.parts
            and "site-packages" not in path.parts
        ):
            found[name] = path
    return found


def _changed(seen: dict[str, float], name: str, mtime: float | None) -> bool:
    if mtime is None:
        return True  # deleted by the pull: stale by definition
    if name in seen:
        return seen[name] != mtime
    return mtime > seen.get(_STARTED, float("inf"))


def drop_stale(root: Path) -> list[str]:
    """If any repo module is stale, drop them all; return the names removed."""
    first_run = not hasattr(sys, _STATE_ATTR)
    seen: dict[str, float] = getattr(sys, _STATE_ATTR, {_STARTED: time.time()})
    modules = _repo_modules(root)
    mtimes: dict[str, float | None] = {}
    for name, path in modules.items():
        try:
            mtimes[name] = path.stat().st_mtime
        except OSError:
            mtimes[name] = None
    stale = first_run or any(_changed(seen, n, m) for n, m in mtimes.items())
    dropped = []
    if stale:
        for name in modules:
            # The reloader is refreshed by Home.py, not by itself.
            if name != __name__:
                del sys.modules[name]
                dropped.append(name)
    seen.update({n: m for n, m in mtimes.items() if m is not None})
    setattr(sys, _STATE_ATTR, seen)
    return dropped
