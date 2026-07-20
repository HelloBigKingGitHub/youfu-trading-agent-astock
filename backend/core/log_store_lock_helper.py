"""Cross-process fcntl.flock helper for the JSONL ``meta.json`` write path.

Phase 3d fixes :mod:`docs.DDD_OPERATIONS` §6.1 — :class:`LogWriter._write_meta`
reads-modifies-writes ``meta.json`` without any lock, so two processes that
finish / update the same task can clobber each other's fields.

This helper does NOT touch :mod:`backend.core.log_store` (per the hard
constraints).  Instead, ``DualWriteLogWriter`` consults the helper at call
time and grabs a process-wide flock on a sibling ``meta.lock`` file before
delegating the underlying write to the legacy writer.  SQLite is unaffected
because WAL already serializes cross-process writes.

Only active when ``DUAL_WRITE_LOGS=1`` — the JSONL path is read-only during
single-write mode so the bug is dormant.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class MetaJsonLockError(RuntimeError):
    """Raised when a cross-process flock acquisition fails."""


@contextlib.contextmanager
def meta_json_lock(
    meta_path: Path,
    *,
    timeout_sec: float = 5.0,
    blocking: bool = True,
) -> Iterator[None]:
    """Acquire an exclusive fcntl.flock on ``meta_path.with_suffix('.lock')``.

    The lock file is created if it doesn't exist.  ``fcntl.flock`` is held
    for the duration of the ``with`` block and released on context exit.

    Parameters
    ----------
    meta_path:
        Path to the ``meta.json`` file we are about to write.  The lock
        is taken on the sibling ``meta.lock``.
    timeout_sec:
        Maximum time to wait for the lock when ``blocking=True``.  If
        ``os.getpid()`` does not acquire within the window we raise
        :class:`MetaJsonLockError` (the caller is expected to swallow it
        and continue — the dual-write path treats the JSONL side as
        best-effort).
    blocking:
        If False, fail immediately with ``MetaJsonLockError`` when the
        lock is held by another process.

    Notes
    -----
    fcntl.flock is per-OS-file-descriptor, but the kernel ties the lock to
    the (inode, file) pair so multiple processes opening the same path all
    serialize through the same lock object.  This is exactly what the
    LogWriter needs.
    """
    lock_path = meta_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        op = fcntl.LOCK_EX | (fcntl.LOCK_NB if not blocking else 0)
        if blocking:
            acquired = _acquire_with_timeout(fd, op, timeout_sec)
            if not acquired:
                raise MetaJsonLockError(
                    f"could not acquire flock on {lock_path} within {timeout_sec}s"
                )
        else:
            try:
                fcntl.flock(fd, op)
            except BlockingIOError as exc:
                raise MetaJsonLockError(
                    f"meta.json lock already held by another process: {lock_path}"
                ) from exc
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def _acquire_with_timeout(fd: int, op: int, timeout_sec: float) -> bool:
    """Try ``fcntl.flock(fd, op | LOCK_NB)`` in a polling loop.

    Returns True on success, False on timeout.  We avoid threads because the
    call sites are inside ``DualWriteLogWriter.update_stages`` /
    ``finalize``, which already run on a LangGraph worker thread.
    """
    import time

    deadline = time.monotonic() + timeout_sec
    nb_op = op | fcntl.LOCK_NB
    while True:
        try:
            fcntl.flock(fd, nb_op)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


def is_dual_write_active() -> bool:
    """Return True iff DUAL_WRITE_LOGS=1 — i.e. JSONL is being written."""
    return os.environ.get("DUAL_WRITE_LOGS", "0") == "1"


__all__ = [
    "MetaJsonLockError",
    "is_dual_write_active",
    "meta_json_lock",
]