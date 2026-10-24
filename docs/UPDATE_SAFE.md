# Snapshot-first update / rollback

0.8.0 adds `scripts/update-safe.ps1`.

The updater refuses an active StreamCopy by default, creates a SQLite-consistent state snapshot under `data/update-snapshots/<timestamp>`, records the current commit, fetches/switches the runtime, builds the frontend, runs lint/tests, and rolls the runtime back to the previous commit if validation fails.

Run:

```powershell
npm run update:safe:win
```

Transfer payloads are not copied into the state snapshot. Existing `.dspart` files remain on their target volumes and are recovered through the River Keeper journal.
