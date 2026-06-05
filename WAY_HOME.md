# The Way Home

Local backup and restore-verification tooling for Ombre Brain.

## Current Trial Scope

- Creates consistent SQLite snapshots with the SQLite Backup API.
- Copies registered Markdown and sensitive persistent files.
- Rejects unknown persistent files.
- Produces a ZIP archive, `manifest.json`, and overall `.sha256` file.
- Verifies hashes, SQLite integrity, Markdown loading, and a basic restored-memory search.
- Rejects unsafe ZIP and manifest paths.
- Writes a `.verification.json` report beside the archive.
- Exposes a protected production export endpoint.
- Coordinates backup snapshots with memory/proposal writes through a shared gate.

Production export requires `OMBRE_BACKUP_TOKEN` and does not accept credentials in
the URL. Backup snapshots wait for active memory/proposal writes, and new writes wait
while a snapshot is active or already queued.

## Create A Local Backup

Keep the output directory outside the Git repository.

```powershell
python way_home.py backup `
  --buckets-dir .\buckets `
  --output-dir "D:\Documents\For Claude\The-Way-Home-backups" `
  --type daily `
  --app-commit 474033f
```

Use `--exclude-derived` to omit `embeddings.db` and `dehydration_cache.db`.

## Verify A Backup

```powershell
python way_home.py verify `
  "D:\Documents\For Claude\The-Way-Home-backups\ombre-backup-....zip"
```

A backup with no Markdown memories can pass structural and SQLite verification, but it
will not report the full `Backup verified and restorable` result because the memory
read/search smoke test cannot run.

## Download From Production

Set `OMBRE_BACKUP_TOKEN` locally to the same value configured in Render, then run:

```powershell
python way_home.py download `
  --url "https://ombre-brain-0jwn.onrender.com/api/backup/export" `
  --output-dir "D:\Documents\For Claude\The-Way-Home-backups" `
  --type daily `
  --verify
```

The production service only returns the archive. The download command writes the
sidecar `.sha256` locally from the response header and verifies the saved archive.

For disaster procedures, see [WAY_HOME_RUNBOOK.md](WAY_HOME_RUNBOOK.md).
