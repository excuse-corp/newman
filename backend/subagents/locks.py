from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


WORKSPACE_MUTATION_LOCK = "__workspace_mutation__"


@dataclass(frozen=True)
class FileLockTimeout(Exception):
    key: str
    blocked_task_id: str
    holding_task_id: str | None

    def __str__(self) -> str:
        holder = self.holding_task_id or "unknown"
        return f"Timed out waiting for file lock {self.key}; holder={holder}"


class FileLockManager:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._holders: dict[str, str] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(
        self,
        keys: list[str],
        *,
        task_id: str,
        timeout_seconds: float,
    ) -> AsyncIterator[list[str]]:
        acquired = await self.acquire(keys, task_id=task_id, timeout_seconds=timeout_seconds)
        try:
            yield acquired
        finally:
            self.release(acquired, task_id=task_id)

    async def acquire(self, keys: list[str], *, task_id: str, timeout_seconds: float) -> list[str]:
        lock_keys = sorted(_normalize_lock_keys(keys))
        if not lock_keys:
            return []

        acquired: list[str] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(timeout_seconds, 0)
        try:
            for key in lock_keys:
                lock = await self._lock_for(key)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise FileLockTimeout(key=key, blocked_task_id=task_id, holding_task_id=self._holders.get(key))
                try:
                    await asyncio.wait_for(lock.acquire(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise FileLockTimeout(key=key, blocked_task_id=task_id, holding_task_id=self._holders.get(key)) from exc
                self._holders[key] = task_id
                acquired.append(key)
            return acquired
        except Exception:
            self.release(acquired, task_id=task_id)
            raise

    def release(self, keys: list[str], *, task_id: str) -> None:
        for key in reversed(keys):
            lock = self._locks.get(key)
            if lock is None:
                continue
            if self._holders.get(key) != task_id:
                continue
            self._holders.pop(key, None)
            if lock.locked():
                lock.release()

    def holder_for(self, key: str) -> str | None:
        return self._holders.get(key)

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock


def path_lock_key(path: Path | str) -> str:
    if isinstance(path, Path):
        try:
            return str(path.resolve())
        except OSError:
            return str(path)
    return str(path)


def workspace_mutation_lock_key() -> str:
    return WORKSPACE_MUTATION_LOCK


def _normalize_lock_keys(keys: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = str(key).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
