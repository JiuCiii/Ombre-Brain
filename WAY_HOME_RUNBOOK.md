# The Way Home Runbook

Disaster backup and restore procedure for Ombre Brain.

## Red Lines

- Never commit plaintext memories, SQLite databases, or backup ZIP files to Git.
- Never put `OMBRE_BACKUP_TOKEN` in a URL.
- Never restore directly into production as the first step.
- Never overwrite production data until a temporary restore has passed verification
  and a human has inspected the restored data.

## Routine Backup

Prerequisites:

- The deployed service includes `POST /api/backup/export`.
- Render has `OMBRE_BACKUP_TOKEN` configured.
- The same token is available locally as an environment variable.
- Local output directory is outside the Git repository.

Command:

```powershell
python way_home.py download `
  --url "https://ombre-brain-0jwn.onrender.com/api/backup/export" `
  --output-dir "D:\Documents\For Claude\The-Way-Home-backups" `
  --type daily `
  --verify
```

Success criteria:

- A `.zip` archive exists outside the repository.
- A matching `.zip.sha256` file exists.
- A `.zip.verification.json` report exists.
- The report says `Backup verified and restorable`.

If there are no Markdown memories in the source being backed up, the report may say
`Backup structurally verified; memory smoke test not applicable`. That is acceptable
only for local empty-bucket trials, not for a real production backup.

## Milestone Backup

Run this before and after major migrations, schema changes, or memory lifecycle
changes:

```powershell
python way_home.py download `
  --url "https://ombre-brain-0jwn.onrender.com/api/backup/export" `
  --output-dir "D:\Documents\For Claude\The-Way-Home-backups" `
  --type milestone `
  --verify
```

Milestone backups are retained permanently unless there is a specific privacy or
security reason to remove them.

## Verify Existing Archive

```powershell
python way_home.py verify `
  "D:\Documents\For Claude\The-Way-Home-backups\ombre-backup-....zip"
```

The verifier checks:

- Overall archive SHA-256 sidecar.
- Unsafe ZIP paths and manifest paths.
- Per-file SHA-256 from `manifest.json`.
- SQLite `PRAGMA integrity_check`.
- Markdown frontmatter loading.
- Basic restored-memory search when Markdown memories exist.

## Temporary Restore Drill

This is the safe first step during a real incident.

1. Pick the newest verified backup, or the most relevant milestone/incident backup.
2. Run `python way_home.py verify <archive>`.
3. Inspect the generated `.verification.json`.
4. Unzip the archive only into a new temporary directory.
5. Inspect `manifest.json` and confirm expected files are present:
   - Markdown buckets
   - `.ombre/trash/`
   - `.ombre/audit.db`
   - `.ombre/proposals.db`
   - derived databases, if included
6. Start a temporary Ombre Brain instance pointed at the restored directory.
7. Confirm Dashboard can list memories, trash, proposals, and audit history.
8. Confirm search/recall works on restored memories.

Do not modify production during this drill.

## Production Replacement

Only proceed when:

- The current production data is already copied aside as an incident backup if it is
  still readable.
- The chosen archive has a passing verification report.
- Temporary restore inspection passed.
- The operator explicitly agrees to replace production data.

High-level steps:

1. Stop the production service or otherwise prevent writes.
2. Copy the current production `buckets/` directory aside as an incident backup.
3. Replace production `buckets/` with the verified restored directory.
4. Start the service.
5. Check `/health`.
6. Check Dashboard memory count, trash, proposals, audit history, and search.
7. Create a fresh post-restore milestone backup and verify it.

## Failure Handling

- `401 Unauthorized`: token missing or wrong; check local env and Render env.
- `409 import is running`: pause or wait for import, then retry.
- `409 backup export already running`: wait for the active export to finish.
- `Unregistered persistent assets`: update the asset registry before trusting the backup.
- SHA mismatch: discard the archive and create/download a new one.
- SQLite integrity failure: do not restore; investigate the source database and try an
  earlier verified backup.
