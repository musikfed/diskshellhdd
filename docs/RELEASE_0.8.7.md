# DiskShell 0.8.7

## Per-view workspace isolation

- Scan, Storage Planner, Diagnostics, Security, Vault and StreamCopy no longer keep working paths or transient job ids in browser-wide `localStorage`.
- View-owned job ids are stored in the backend `workspace_views` row for that `view_id`, with per-view `sessionStorage` only as a browser fallback.
- The promoted default workspace strips transient job ids. A new tab can inherit useful navigation and paths without inheriting another tab's running job.
- StreamCopy reconnects only to the job explicitly owned by the current view. It no longer adopts the globally latest active or last job.

## SFTP tree safety

- SFTP metadata uses `lstat` so symbolic links are identified without following their targets.
- Remote manifest walking skips symbolic links, matching the local scanner policy for links/junctions.
- Recursive remote delete removes a symbolic link itself rather than traversing into the linked directory tree.

## Cleanup

Removed obsolete global browser-state persistence for the affected admin workflows. No functional storage module was removed.

## Validation

Regression coverage was added for default-workspace transient-job filtering and SFTP symlink-safe metadata/tree walking.

Disk and extent write safety semantics are unchanged.
