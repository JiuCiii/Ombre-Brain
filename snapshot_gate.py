"""Async coordination between memory writes and backup snapshots."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class SnapshotWriteGate:
    """Allow many writes or one snapshot, but never both at the same time."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_writers = 0
        self._snapshot_active = False
        self._waiting_snapshots = 0
        self._writer_tasks: dict[asyncio.Task, int] = {}

    @asynccontextmanager
    async def writer(self):
        task = asyncio.current_task()
        if task in self._writer_tasks:
            async with self._condition:
                self._active_writers += 1
                self._writer_tasks[task] += 1
            try:
                yield
            finally:
                async with self._condition:
                    self._active_writers -= 1
                    self._writer_tasks[task] -= 1
                    if self._writer_tasks[task] == 0:
                        del self._writer_tasks[task]
                    if self._active_writers == 0:
                        self._condition.notify_all()
            return

        async with self._condition:
            while self._snapshot_active or self._waiting_snapshots > 0:
                await self._condition.wait()
            self._active_writers += 1
            self._writer_tasks[task] = self._writer_tasks.get(task, 0) + 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_writers -= 1
                self._writer_tasks[task] -= 1
                if self._writer_tasks[task] == 0:
                    del self._writer_tasks[task]
                if self._active_writers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def snapshot(self):
        async with self._condition:
            self._waiting_snapshots += 1
            try:
                while self._snapshot_active or self._active_writers > 0:
                    await self._condition.wait()
                self._snapshot_active = True
            finally:
                self._waiting_snapshots -= 1
        try:
            yield
        finally:
            async with self._condition:
                self._snapshot_active = False
                self._condition.notify_all()

    @property
    def snapshot_active(self) -> bool:
        return self._snapshot_active

    @property
    def active_writers(self) -> int:
        return self._active_writers

    @property
    def waiting_snapshots(self) -> int:
        return self._waiting_snapshots
