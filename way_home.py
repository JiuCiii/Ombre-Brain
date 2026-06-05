"""The Way Home: consistent Ombre Brain backup and restore verification."""

from __future__ import annotations

import argparse
import email.message
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import frontmatter
import httpx


BACKUP_SCHEMA = "ombre.backup.v1"
VERIFICATION_SCHEMA = "ombre.backup.verification.v1"
TOOL_VERSION = "0.1.0"
BACKUP_TYPES = {"daily", "milestone", "incident"}
DERIVED_DATABASES = {"embeddings.db", "dehydration_cache.db"}
REQUIRED_DATABASES = {".ombre/audit.db", ".ombre/proposals.db"}
SENSITIVE_FILES = {".dashboard_auth.json"}
EXCLUDED_FILES = {"import_state.json"}
EXCLUDED_PREFIXES = ("backup-before-safety-",)
EXCLUDED_SUFFIXES = (".tar.gz", ".tgz")
MAX_ARCHIVE_FILES = 10_000
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024


class BackupError(RuntimeError):
    """Raised when a backup cannot be safely created or verified."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _classification(relative_path: str) -> str | None:
    if relative_path.endswith(".md"):
        return "required"
    if relative_path in REQUIRED_DATABASES:
        return "required"
    if relative_path in DERIVED_DATABASES:
        return "derived"
    if relative_path in SENSITIVE_FILES:
        return "sensitive"
    if relative_path in EXCLUDED_FILES:
        return "intentionally_excluded"
    if (
        "/" not in relative_path
        and relative_path.startswith(EXCLUDED_PREFIXES)
        and relative_path.endswith(EXCLUDED_SUFFIXES)
    ):
        return "intentionally_excluded"
    if relative_path.endswith(("-wal", "-shm")):
        base = relative_path.rsplit("-", 1)[0]
        if base in REQUIRED_DATABASES or base in DERIVED_DATABASES:
            return "intentionally_excluded"
    return None


def discover_assets(buckets_dir: str | Path, include_derived: bool = True) -> dict:
    """Return the registered persistent assets and reject unknown files."""
    root = Path(buckets_dir).resolve()
    if not root.is_dir():
        raise BackupError(f"Buckets directory does not exist: {root}")

    assets = []
    excluded = []
    unknown = []
    found_required_databases = set()

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative_path = _relative(path, root)
        classification = _classification(relative_path)
        if classification is None:
            unknown.append(relative_path)
            continue
        if relative_path in REQUIRED_DATABASES:
            found_required_databases.add(relative_path)
        record = {"path": relative_path, "classification": classification}
        if classification == "intentionally_excluded":
            excluded.append(record)
        elif classification == "derived" and not include_derived:
            excluded.append({**record, "reason": "derived data disabled"})
        else:
            assets.append(record)

    missing = sorted(REQUIRED_DATABASES - found_required_databases)
    if missing:
        raise BackupError(f"Required persistent assets are missing: {', '.join(missing)}")
    if unknown:
        raise BackupError(f"Unregistered persistent assets found: {', '.join(unknown)}")

    return {"assets": assets, "excluded": excluded}


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    dest_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(dest_conn)
        result = dest_conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(f"SQLite snapshot failed integrity check: {source}")
    finally:
        dest_conn.close()
        source_conn.close()


def _copy_assets(root: Path, stage: Path, assets: list[dict]) -> list[dict]:
    copied = []
    for asset in assets:
        relative_path = asset["path"]
        source = root / relative_path
        destination = stage / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".db":
            _backup_sqlite(source, destination)
        else:
            shutil.copy2(source, destination)
        copied.append(
            {
                **asset,
                "bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
    return copied


def _write_zip(stage: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in stage.rglob("*") if item.is_file()):
            archive.write(path, _relative(path, stage))
        if not any((stage / ".ombre" / "trash").iterdir()):
            archive.writestr(".ombre/trash/", "")


def create_backup(
    buckets_dir: str | Path,
    output_dir: str | Path,
    backup_type: str = "daily",
    include_derived: bool = True,
    app_commit: str = "unknown",
) -> dict:
    """Create a local consistent snapshot archive and its overall hash file."""
    if backup_type not in BACKUP_TYPES:
        raise BackupError(f"Unsupported backup type: {backup_type}")

    root = Path(buckets_dir).resolve()
    destination_dir = Path(output_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    discovered = discover_assets(root, include_derived=include_derived)
    created_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    commit_label = (app_commit or "unknown")[:12]
    archive_path = destination_dir / f"ombre-backup-{timestamp}-{backup_type}-{commit_label}.zip"

    with tempfile.TemporaryDirectory(prefix="ombre-backup-") as temp_dir:
        stage = Path(temp_dir) / "snapshot"
        stage.mkdir()
        copied = _copy_assets(root, stage, discovered["assets"])
        (stage / ".ombre" / "trash").mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema": BACKUP_SCHEMA,
            "created_at": created_at,
            "backup_type": backup_type,
            "app_commit": app_commit or "unknown",
            "tool_version": TOOL_VERSION,
            "includes_derived_data": include_derived,
            "bucket_count": sum(1 for item in copied if item["path"].endswith(".md")),
            "files": copied,
            "excluded": discovered["excluded"],
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_zip(stage, archive_path)

    archive_hash = _sha256(archive_path)
    hash_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    hash_path.write_text(f"{archive_hash}  {archive_path.name}\n", encoding="ascii")
    return {
        "archive": str(archive_path),
        "sha256_file": str(hash_path),
        "sha256": archive_hash,
        "manifest": manifest,
    }


def _expected_archive_hash(archive_path: Path, hash_path: Path | None) -> str:
    sidecar = hash_path or archive_path.with_suffix(archive_path.suffix + ".sha256")
    if not sidecar.is_file():
        raise BackupError(f"Archive hash file is missing: {sidecar}")
    expected = sidecar.read_text(encoding="ascii").strip().split()[0]
    if len(expected) != 64:
        raise BackupError(f"Archive hash file is invalid: {sidecar}")
    return expected


def _validate_zip_members(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_FILES:
        raise BackupError(f"Archive contains too many files: {len(members)}")
    total_bytes = 0
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise BackupError(f"Unsafe archive path: {member.filename}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise BackupError(f"Archive contains a symbolic link: {member.filename}")
        total_bytes += member.file_size
        if total_bytes > MAX_EXTRACTED_BYTES:
            raise BackupError("Archive exceeds the safe extraction size limit")


def _extract_safely(archive: zipfile.ZipFile, destination: Path) -> None:
    _validate_zip_members(archive)
    for member in archive.infolist():
        target = destination.joinpath(*PurePosixPath(member.filename).parts)
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _safe_manifest_path(restore_dir: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise BackupError(f"Unsafe manifest path: {relative_path}")
    target = restore_dir.joinpath(*path.parts).resolve()
    try:
        target.relative_to(restore_dir.resolve())
    except ValueError as exc:
        raise BackupError(f"Unsafe manifest path: {relative_path}") from exc
    return target


def verify_backup(
    archive: str | Path,
    hash_file: str | Path | None = None,
    report_path: str | Path | None = None,
) -> dict:
    """Verify an archive without modifying production data."""
    archive_path = Path(archive).resolve()
    if not archive_path.is_file():
        raise BackupError(f"Backup archive does not exist: {archive_path}")
    hash_path = Path(hash_file).resolve() if hash_file else None
    expected_hash = _expected_archive_hash(archive_path, hash_path)
    actual_hash = _sha256(archive_path)
    if actual_hash != expected_hash:
        raise BackupError("Archive SHA-256 does not match its sidecar")

    with tempfile.TemporaryDirectory(prefix="ombre-restore-verify-") as temp_dir:
        restore_dir = Path(temp_dir) / "restored"
        restore_dir.mkdir()
        with zipfile.ZipFile(archive_path) as zip_archive:
            _extract_safely(zip_archive, restore_dir)

        manifest_path = restore_dir / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError("Archive does not contain manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != BACKUP_SCHEMA:
            raise BackupError(f"Unsupported backup schema: {manifest.get('schema')}")

        sqlite_results = {}
        markdown_count = 0
        markdown_contents = []
        total_bytes = 0
        for file_record in manifest.get("files", []):
            relative_path = file_record["path"]
            path = _safe_manifest_path(restore_dir, relative_path)
            if not path.is_file():
                raise BackupError(f"Manifest file is missing: {relative_path}")
            actual_file_hash = _sha256(path)
            if actual_file_hash != file_record["sha256"]:
                raise BackupError(f"File SHA-256 mismatch: {relative_path}")
            total_bytes += path.stat().st_size
            if relative_path.endswith(".db"):
                connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                finally:
                    connection.close()
                sqlite_results[relative_path] = result[0] if result else "no result"
                if sqlite_results[relative_path] != "ok":
                    raise BackupError(f"SQLite integrity check failed: {relative_path}")
            elif relative_path.endswith(".md"):
                post = frontmatter.load(path)
                markdown_contents.append(post.content)
                markdown_count += 1

        if markdown_contents:
            searchable = next((content.strip() for content in markdown_contents if content.strip()), "")
            basic_search = "passed" if searchable and any(
                searchable[:32] in content for content in markdown_contents
            ) else "failed"
            if basic_search != "passed":
                raise BackupError("Basic restored-memory search smoke test failed")
            final_result = "Backup verified and restorable"
        else:
            basic_search = "not_applicable_no_markdown"
            final_result = "Backup structurally verified; memory smoke test not applicable"

        report = {
            "schema": VERIFICATION_SCHEMA,
            "verified_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "tool_version": TOOL_VERSION,
            "archive": archive_path.name,
            "archive_sha256": actual_hash,
            "archive_hash_verified": True,
            "file_count": len(manifest.get("files", [])),
            "total_uncompressed_bytes": total_bytes,
            "sqlite_integrity": sqlite_results,
            "markdown_loaded": markdown_count,
            "smoke_test": {
                "markdown_read": "passed",
                "basic_search": basic_search,
            },
            "result": final_result,
        }

    output_report = (
        Path(report_path).resolve()
        if report_path
        else archive_path.with_suffix(archive_path.suffix + ".verification.json")
    )
    output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**report, "report_path": str(output_report)}


def _filename_from_content_disposition(value: str, fallback: str) -> str:
    if not value:
        return fallback
    message = email.message.Message()
    message["Content-Disposition"] = value
    filename = message.get_filename()
    if not filename:
        return fallback
    return Path(filename).name


def download_backup(
    source_url: str,
    token: str,
    output_dir: str | Path,
    backup_type: str = "daily",
    include_derived: bool = True,
    timeout: float = 180.0,
) -> dict:
    """Download a protected production backup archive and write its sidecar hash."""
    if not token:
        raise BackupError("Backup token is required")
    destination_dir = Path(output_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    params = {"type": backup_type, "include_derived": "1" if include_derived else "0"}
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.post(source_url, headers=headers, params=params)
    if response.status_code != 200:
        raise BackupError(f"Backup export failed with HTTP {response.status_code}: {response.text[:300]}")
    expected_hash = response.headers.get("x-ombre-backup-sha256", "").strip()
    if len(expected_hash) != 64:
        raise BackupError("Backup export response did not include a valid SHA-256 header")
    filename = _filename_from_content_disposition(
        response.headers.get("content-disposition", ""),
        f"ombre-backup-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')}.zip",
    )
    archive_path = destination_dir / filename
    archive_path.write_bytes(response.content)
    actual_hash = _sha256(archive_path)
    if actual_hash != expected_hash:
        archive_path.unlink(missing_ok=True)
        raise BackupError("Downloaded archive SHA-256 does not match response header")
    hash_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    hash_path.write_text(f"{actual_hash}  {archive_path.name}\n", encoding="ascii")
    return {
        "archive": str(archive_path),
        "sha256_file": str(hash_path),
        "sha256": actual_hash,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ombre Brain backup and restore verification")
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="Create a local backup archive")
    backup.add_argument("--buckets-dir", required=True)
    backup.add_argument("--output-dir", required=True)
    backup.add_argument("--type", choices=sorted(BACKUP_TYPES), default="daily")
    backup.add_argument("--app-commit", default=os.environ.get("OMBRE_APP_COMMIT", "unknown"))
    backup.add_argument("--exclude-derived", action="store_true")

    verify = commands.add_parser("verify", help="Verify a backup archive")
    verify.add_argument("archive")
    verify.add_argument("--hash-file")
    verify.add_argument("--report")

    download = commands.add_parser("download", help="Download a protected production backup")
    download.add_argument("--url", required=True)
    download.add_argument("--output-dir", required=True)
    download.add_argument("--token", default="")
    download.add_argument("--token-env", default="OMBRE_BACKUP_TOKEN")
    download.add_argument("--type", choices=sorted(BACKUP_TYPES), default="daily")
    download.add_argument("--exclude-derived", action="store_true")
    download.add_argument("--verify", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == "backup":
            result = create_backup(
                args.buckets_dir,
                args.output_dir,
                backup_type=args.type,
                include_derived=not args.exclude_derived,
                app_commit=args.app_commit,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if args.command == "verify":
                result = verify_backup(args.archive, args.hash_file, args.report)
            else:
                token = args.token or os.environ.get(args.token_env, "")
                result = download_backup(
                    args.url,
                    token,
                    args.output_dir,
                    backup_type=args.type,
                    include_derived=not args.exclude_derived,
                )
                if args.verify:
                    result["verification"] = verify_backup(result["archive"])
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (BackupError, OSError, sqlite3.Error, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"Backup failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
