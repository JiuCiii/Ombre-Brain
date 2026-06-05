import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from way_home import BackupError, create_backup, discover_assets, verify_backup


def _seed_buckets(root: Path) -> None:
    (root / "dynamic" / "test").mkdir(parents=True)
    (root / ".ombre" / "trash").mkdir(parents=True)
    (root / "dynamic" / "test" / "memory.md").write_text(
        "---\nid: test-memory\nname: Test\n---\nA memory\n",
        encoding="utf-8",
    )
    for relative_path, table in [
        (".ombre/audit.db", "audit_events"),
        (".ombre/proposals.db", "proposals"),
        ("embeddings.db", "embeddings"),
    ]:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.execute(f"INSERT INTO {table} DEFAULT VALUES")
    (root / ".dashboard_auth.json").write_text('{"hash":"secret-hash"}', encoding="utf-8")
    (root / "import_state.json").write_text('{"running":true}', encoding="utf-8")


def test_create_and_verify_backup(tmp_path):
    buckets = tmp_path / "buckets"
    output = tmp_path / "backups"
    _seed_buckets(buckets)

    created = create_backup(buckets, output, app_commit="abc123")
    report = verify_backup(created["archive"])

    assert report["result"] == "Backup verified and restorable"
    assert report["markdown_loaded"] == 1
    assert report["smoke_test"]["basic_search"] == "passed"
    assert report["sqlite_integrity"][".ombre/audit.db"] == "ok"
    assert Path(report["report_path"]).is_file()
    assert any(
        item["path"] == ".dashboard_auth.json"
        and item["classification"] == "sensitive"
        for item in created["manifest"]["files"]
    )
    assert any(
        item["path"] == "import_state.json"
        for item in created["manifest"]["excluded"]
    )
    with zipfile.ZipFile(created["archive"]) as archive:
        assert ".ombre/trash/" in archive.namelist()


def test_unknown_persistent_asset_stops_backup(tmp_path):
    buckets = tmp_path / "buckets"
    _seed_buckets(buckets)
    (buckets / "new_state.bin").write_bytes(b"unknown")

    with pytest.raises(BackupError, match="Unregistered persistent assets"):
        discover_assets(buckets)


def test_archive_hash_corruption_is_detected(tmp_path):
    buckets = tmp_path / "buckets"
    _seed_buckets(buckets)
    created = create_backup(buckets, tmp_path / "backups")
    archive = Path(created["archive"])
    archive.write_bytes(archive.read_bytes() + b"corruption")

    with pytest.raises(BackupError, match="SHA-256"):
        verify_backup(archive)


def test_unsafe_archive_path_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "bad")
        output.writestr("manifest.json", json.dumps({"schema": "ombre.backup.v1", "files": []}))
    import hashlib

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  unsafe.zip\n", encoding="ascii")

    with pytest.raises(BackupError, match="Unsafe archive path"):
        verify_backup(archive)


def test_unsafe_manifest_path_is_rejected(tmp_path):
    archive = tmp_path / "unsafe-manifest.zip"
    manifest = {
        "schema": "ombre.backup.v1",
        "files": [{"path": "../outside.txt", "sha256": "0" * 64}],
    }
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
    import hashlib

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(
        f"{digest}  unsafe-manifest.zip\n",
        encoding="ascii",
    )

    with pytest.raises(BackupError, match="Unsafe manifest path"):
        verify_backup(archive)
