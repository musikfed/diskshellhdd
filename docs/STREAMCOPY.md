# StreamCopy EXP 0.7.5 · River Keeper

StreamCopy is a separate experimental local-copy engine. The regular Commander remains a separate transfer manager.

A folder is treated as one logical data river: persistent manifest → producer → bounded RAM queue → consumer → job-specific `.dspart` → verified publish.

RAM is only a bounded working buffer. Transfer state lives in SQLite `data/diskshell.db`: job profile, local volume identities, manifest items, source size/mtime, item status, confirmed offsets, checkpoint hashes, progress, warnings, and lease ownership.

The default checkpoint is **128 MiB**. After an interruption StreamCopy does not trust an arbitrary partial-file size. It walks backward through persisted checkpoints and compares the stored digest with SHA-256 of the corresponding source and partial ranges. Only a verified checkpoint is accepted; the unverified tail is truncated and rewritten. If no checkpoint is safe, only the current file returns to offset 0. Already completed files remain completed.

Local endpoints are bound to stable volume identity. Hot-unplug changes the job to `waiting_endpoint`; when the same volume identity returns the job verifies its checkpoint and resumes.

Backend restart is recoverable. Active jobs are persisted, and a recovery manager claims unfinished jobs after the previous backend lease expires. `lease_owner + lease_expires_at` prevents two live backend instances from intentionally owning the same job.

The browser remains a control surface. Refresh, tab close, browser-site-data cleanup, or opening another browser do not own or destroy the persistent transfer state.

StreamCopy deliberately has no destructive Move primitive:

- **COPY** keeps the source and supports Size or SHA-256 verification.
- **COPY → SHA-256 → DELETE SOURCE** forces strong verification, publishes the target first, then deletes only the corresponding verified source file.

Existing final targets are never silently overwritten. Job-specific partial files are separate from final targets.

0.7.5 River Keeper is local-only. Remote SFTP/FTP StreamCopy, extent-order scheduling, and RAW placement remain outside this experimental engine.
