"""Backfill safety metadata on legacy Ombre Brain Markdown buckets.

Dry-run is the default. Pass --apply to write changes.
"""

import argparse
import os
from pathlib import Path

import frontmatter

from audit_ledger import AuditLedger
from utils import load_config


DEFAULT_FIELDS = {
    "source_type": "legacy",
    "memory_kind": "memory",
    "scope": "global",
    "matched_count": 0,
    "recalled_count": 0,
    "confirmed_count": 0,
}


def migrate(buckets_dir: str, apply: bool = False) -> dict:
    base_dir = Path(buckets_dir).resolve()
    ledger = AuditLedger(str(base_dir))
    report = {"scanned": 0, "changed": 0, "written": 0, "errors": []}

    for folder in ("permanent", "dynamic", "archive", "feel"):
        root = base_dir / folder
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            report["scanned"] += 1
            try:
                post = frontmatter.load(path)
                additions = {
                    key: value for key, value in DEFAULT_FIELDS.items()
                    if key not in post.metadata
                }
                if not additions:
                    continue
                report["changed"] += 1
                if not apply:
                    continue

                before = ledger.snapshot_file(str(path))
                for key, value in additions.items():
                    post[key] = value
                path.write_text(frontmatter.dumps(post), encoding="utf-8")
                bucket_id = str(post.get("id", path.stem))
                ledger.record(
                    bucket_id,
                    "metadata_migration",
                    before=before,
                    after=ledger.snapshot_file(str(path)),
                    actor="migrate_safety_metadata",
                    reason="backfill legacy safety metadata",
                )
                report["written"] += 1
            except Exception as exc:
                report["errors"].append({"path": str(path), "error": str(exc)})

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Ombre Brain safety metadata.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--buckets-dir", default="", help="Override configured buckets directory.")
    args = parser.parse_args()

    config = load_config()
    buckets_dir = args.buckets_dir or config["buckets_dir"]
    report = migrate(buckets_dir, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode}: scanned={report['scanned']} changed={report['changed']} "
        f"written={report['written']} errors={len(report['errors'])}"
    )
    for error in report["errors"]:
        print(f"ERROR {error['path']}: {error['error']}")


if __name__ == "__main__":
    main()
