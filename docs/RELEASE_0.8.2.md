# DiskShell 0.8.2 — StreamCopy v2 Microfile Frames

StreamCopy v2 moves from “one durable folder job” toward a real logical stream for small-file workloads.

Files up to **1 MiB** may be packed by the producer into RAM frames sized to the active stream chunk:

```text
manifest
  -> microfile candidates
  -> producer packs many files into one RAM frame
  -> bounded frame queue
  -> consumer
  -> ordinary destination files
```

For an HDD→HDD 8 MiB profile, many 50–500 KiB files can cross the internal queue as one frame while still being published as normal individual destination files.

Microbatching is only used for pending items with no existing target or recovery partial. On a frame-path failure the engine falls back to the ordinary per-file River Keeper path. Completed items are recognized from the persistent journal and are not blindly recopied.

COPY→SHA-256→DELETE SOURCE keeps the same verify/publish/delete safety order.

Transfer average now excludes manifest planning time. The StreamCopy UI is SSE-first for progress/status, with a slow ~10 second HTTP reconciliation fallback instead of 400 ms polling.

Not yet enabled: automatic NTFS physical-locality scheduling. Remote River over SFTP is the next separate stage.
