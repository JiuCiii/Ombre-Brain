# Ombre Brain Safety Upgrade Release Checklist

## Before Publishing

- Confirm the GitHub repository connected to the production Render service.
- Confirm production has a persistent disk mounted at `OMBRE_BUCKETS_DIR`.
- Back up the complete production buckets directory, including hidden files.
- Keep `merge_mode: proposal` for the first release.

## Deploy

1. Push this release branch to the production repository.
2. Let Render build and deploy the new commit.
3. Verify `/health` returns HTTP 200.
4. Log in to `/dashboard` and open **审核与恢复**.

## Migrate Legacy Memories

Run against the production persistent buckets directory:

```bash
python migrate_safety_metadata.py
python migrate_safety_metadata.py --apply
```

The first command is dry-run only. Review its counts before using `--apply`.

## Smoke Test

- Create a test memory and confirm its source/scope fields appear.
- Create a similar test memory and confirm a merge proposal appears.
- Reject one proposal and confirm both memories remain.
- Approve one proposal and confirm the source enters the recycle bin.
- Restore the source from the recycle bin.
- View one memory's history and perform a rollback.
- Confirm `xiaoke-wake` logs and journal remain unchanged.

## Rollback

- Roll back the Render deployment to the previous commit if startup fails.
- Memory mutations made after this release remain recoverable through
  `.ombre/audit.db` and `.ombre/trash/`.
