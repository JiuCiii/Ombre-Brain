"""Tests for the legacy safety metadata migration."""

import frontmatter

from migrate_safety_metadata import DEFAULT_FIELDS, migrate


def test_migration_dry_run_and_apply(tmp_path):
    bucket_dir = tmp_path / "buckets"
    path = bucket_dir / "dynamic" / "test" / "legacy_abc123.md"
    path.parent.mkdir(parents=True)
    post = frontmatter.Post(
        "legacy content",
        id="abc123",
        name="legacy",
        type="dynamic",
        created="2024-01-01T00:00:00",
        last_active="2024-01-02T00:00:00",
        activation_count=3,
    )
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    dry_run = migrate(str(bucket_dir), apply=False)
    assert dry_run == {"scanned": 1, "changed": 1, "written": 0, "errors": []}
    assert path.read_text(encoding="utf-8") == original

    applied = migrate(str(bucket_dir), apply=True)
    assert applied == {"scanned": 1, "changed": 1, "written": 1, "errors": []}
    migrated = frontmatter.load(path)
    for key, value in DEFAULT_FIELDS.items():
        assert migrated[key] == value
    assert migrated["created"] == "2024-01-01T00:00:00"
    assert migrated["last_active"] == "2024-01-02T00:00:00"
    assert migrated["activation_count"] == 3

    second = migrate(str(bucket_dir), apply=True)
    assert second == {"scanned": 1, "changed": 0, "written": 0, "errors": []}
