# DiskShell 0.8.1 — Commander River

Commander copy/move jobs now have a persistent SQLite journal and lease protection.

Top-level transfer state:

```text
pending -> copying -> verified -> completed
                   \-> skipped / missing
```

Cross-volume/endpoint MOVE follows:

```text
COPY -> verify destination -> persist VERIFIED -> delete source -> persist COMPLETED
```

A backend crash after VERIFIED causes the next worker to verify the target again before source deletion.

After restart, unfinished jobs are rediscovered from SQLite, stale leases can be reclaimed, partial targets provide resume offsets, completed top-level transfers are skipped, and a new browser can discover the active backend job without relying on old localStorage.

Remote credentials are never written to the journal. Persistent remote endpoints keep only a stable identity:

```text
protocol|host|port|username|root
```

After restart, the user recreates an in-memory connection profile. If the identity matches, the job rebinds from the stale connection id to the new one.

SFTP is the primary restart-recovery target in 0.8.1. Commander still uses size-based partial resume rather than StreamCopy's SHA-256 checkpoint river.
