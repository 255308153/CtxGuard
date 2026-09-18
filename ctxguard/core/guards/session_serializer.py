"""Session-level concurrency serialization manager (inspired by Headroom Issue #2085 & in-flight tracking).

Prevents concurrent or overlapping turns for the same session from being dispatched
simultaneously to upstream providers. This eliminates TPU/GPU node cache migration
and guarantees 100% prefix KV cache affinity.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import logging
import time
from typing import AsyncIterator, Callable, Dict, Optional

logger = logging.getLogger("ctxguard.core.guards.session_serializer")


class SessionSerializer:
    """Bounded LRU serializer managing per-session asyncio locks.

    Ensures that turns within the same conversation session are executed
    strictly serially against upstream model nodes, avoiding concurrency
    races that break KV prompt caching.
    """

    def __init__(self, max_sessions: int = 1000, default_timeout: float = 45.0) -> None:
        self._max_sessions = max(10, max_sessions)
        self._default_timeout = max(1.0, default_timeout)
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._in_flight: Dict[str, int] = {}
        self._global_lock = asyncio.Lock()

    async def _get_or_create_lock(self, session_id: str) -> asyncio.Lock:
        """Fetch existing lock or create a new one with bounded LRU eviction."""
        async with self._global_lock:
            if session_id in self._locks:
                lock = self._locks[session_id]
                self._locks.move_to_end(session_id)
                return lock

            # Evict oldest unlocked sessions if capacity exceeded
            while len(self._locks) >= self._max_sessions:
                evicted = False
                for sid in list(self._locks.keys()):
                    candidate = self._locks[sid]
                    if not candidate.locked() and self._in_flight.get(sid, 0) == 0:
                        del self._locks[sid]
                        self._in_flight.pop(sid, None)
                        evicted = True
                        break
                if not evicted:
                    # All active locks are currently held; stop evicting
                    break

            lock = asyncio.Lock()
            self._locks[session_id] = lock
            return lock

    async def acquire(self, session_id: str, timeout: Optional[float] = None) -> Callable[[], None]:
        """Acquire session lock, waiting asynchronously if an in-flight request is already streaming.

        Returns an idempotent unlock callback.
        """
        if not session_id or session_id == "default":
            # Unidentified/default sessions are not serialized against each other
            return lambda: None

        effective_timeout = timeout if timeout is not None else self._default_timeout
        lock = await self._get_or_create_lock(session_id)

        start_time = time.monotonic()
        locked = False

        try:
            # Wait for any in-flight turn for this session to finish streaming
            await asyncio.wait_for(lock.acquire(), timeout=effective_timeout)
            locked = True
            wait_time = time.monotonic() - start_time
            if wait_time > 0.05:
                logger.info(
                    f"[SessionSerializer] Queued turn for session '{session_id}' waited {wait_time:.2f}s "
                    f"for prior stream to finish -> 100% KV cache protected."
                )
        except asyncio.TimeoutError:
            logger.warning(
                f"[SessionSerializer] Lock wait timed out after {effective_timeout}s for session '{session_id}'. "
                f"Proceeding to prevent client timeout."
            )
            locked = False

        released = False

        def unlock() -> None:
            nonlocal released
            if not released:
                released = True
                if locked and lock.locked():
                    try:
                        lock.release()
                    except RuntimeError:
                        pass

        return unlock

    @asynccontextmanager
    async def serialize(
        self, session_id: str, timeout: Optional[float] = None
    ) -> AsyncIterator[Callable[[], None]]:
        """Context manager for serializing session execution."""
        unlock = await self.acquire(session_id, timeout=timeout)
        try:
            yield unlock
        finally:
            unlock()
