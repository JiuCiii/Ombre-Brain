import asyncio
from types import SimpleNamespace
from pathlib import Path
import zipfile

import pytest

from tests.test_way_home import _seed_buckets
from snapshot_gate import SnapshotWriteGate


class _Request:
    def __init__(self, headers=None, query_params=None):
        self.headers = headers or {}
        self.query_params = query_params or {}


@pytest.mark.asyncio
async def test_backup_export_requires_independent_token(monkeypatch):
    import server

    monkeypatch.delenv("OMBRE_BACKUP_TOKEN", raising=False)
    response = await server.api_backup_export(_Request())
    assert response.status_code == 503

    monkeypatch.setenv("OMBRE_BACKUP_TOKEN", "secret")
    response = await server.api_backup_export(_Request(headers={"authorization": "Bearer wrong"}))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_backup_export_returns_archive(monkeypatch, tmp_path):
    import server

    buckets = tmp_path / "buckets"
    _seed_buckets(buckets)
    monkeypatch.setenv("OMBRE_BACKUP_TOKEN", "secret")
    monkeypatch.setattr(server, "config", {**server.config, "buckets_dir": str(buckets)})
    monkeypatch.setattr(server, "backup_export_lock", asyncio.Lock())

    response = await server.api_backup_export(
        _Request(
            headers={"authorization": "Bearer secret"},
            query_params={"type": "daily", "include_derived": "0"},
        )
    )

    assert response.status_code == 200
    assert response.headers["X-Ombre-Backup-Sha256"]
    assert response.headers["Cache-Control"] == "no-store"
    assert Path(response.path).is_file()
    if response.background:
        await response.background()


@pytest.mark.asyncio
async def test_backup_export_refuses_while_import_is_running(monkeypatch):
    import server

    monkeypatch.setenv("OMBRE_BACKUP_TOKEN", "secret")
    monkeypatch.setattr(server, "import_engine", SimpleNamespace(is_running=True))
    response = await server.api_backup_export(
        _Request(headers={"x-ombre-backup-token": "secret"})
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_backup_export_waits_for_active_writer(monkeypatch, tmp_path):
    import server

    events = []
    gate = SnapshotWriteGate()
    monkeypatch.setenv("OMBRE_BACKUP_TOKEN", "secret")
    monkeypatch.setattr(server, "snapshot_write_gate", gate)
    monkeypatch.setattr(server, "backup_export_lock", asyncio.Lock())
    monkeypatch.setattr(server, "config", {**server.config, "buckets_dir": str(tmp_path / "buckets")})

    def fake_create_backup(_buckets_dir, output_dir, **_kwargs):
        events.append("snapshot")
        archive = Path(output_dir) / "backup.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("manifest.json", "{}")
        return {"archive": str(archive), "sha256": "0" * 64}

    monkeypatch.setattr(server, "create_backup", fake_create_backup)

    async def active_writer():
        async with gate.writer():
            events.append("writer-start")
            await asyncio.sleep(0.05)
            events.append("writer-end")

    async def export():
        await asyncio.sleep(0.01)
        response = await server.api_backup_export(
            _Request(headers={"authorization": "Bearer secret"})
        )
        if response.background:
            await response.background()
        assert response.status_code == 200

    await asyncio.gather(active_writer(), export())

    assert events == ["writer-start", "writer-end", "snapshot"]
