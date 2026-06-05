import asyncio

import pytest

from snapshot_gate import SnapshotWriteGate


@pytest.mark.asyncio
async def test_snapshot_waits_for_active_writer():
    gate = SnapshotWriteGate()
    events = []

    async def writer():
        async with gate.writer():
            events.append("writer-start")
            await asyncio.sleep(0.05)
            events.append("writer-end")

    async def snapshot():
        await asyncio.sleep(0.01)
        async with gate.snapshot():
            events.append("snapshot")

    await asyncio.gather(writer(), snapshot())

    assert events == ["writer-start", "writer-end", "snapshot"]


@pytest.mark.asyncio
async def test_writer_waits_for_active_snapshot():
    gate = SnapshotWriteGate()
    events = []

    async def snapshot():
        async with gate.snapshot():
            events.append("snapshot-start")
            await asyncio.sleep(0.05)
            events.append("snapshot-end")

    async def writer():
        await asyncio.sleep(0.01)
        async with gate.writer():
            events.append("writer")

    await asyncio.gather(snapshot(), writer())

    assert events == ["snapshot-start", "snapshot-end", "writer"]


@pytest.mark.asyncio
async def test_waiting_snapshot_prevents_writer_starvation():
    gate = SnapshotWriteGate()
    events = []

    async def first_writer():
        async with gate.writer():
            events.append("first-writer-start")
            await asyncio.sleep(0.05)
            events.append("first-writer-end")

    async def snapshot():
        await asyncio.sleep(0.01)
        async with gate.snapshot():
            events.append("snapshot")

    async def second_writer():
        await asyncio.sleep(0.02)
        async with gate.writer():
            events.append("second-writer")

    await asyncio.gather(first_writer(), snapshot(), second_writer())

    assert events == [
        "first-writer-start",
        "first-writer-end",
        "snapshot",
        "second-writer",
    ]


@pytest.mark.asyncio
async def test_writer_is_reentrant_even_when_snapshot_waits():
    gate = SnapshotWriteGate()
    events = []

    async def writer():
        async with gate.writer():
            events.append("outer-start")
            await asyncio.sleep(0.03)
            async with gate.writer():
                events.append("inner")
            events.append("outer-end")

    async def snapshot():
        await asyncio.sleep(0.01)
        async with gate.snapshot():
            events.append("snapshot")

    await asyncio.gather(writer(), snapshot())

    assert events == ["outer-start", "inner", "outer-end", "snapshot"]
