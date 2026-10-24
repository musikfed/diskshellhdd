# DiskShell 0.8.6 — Multi-view workspace + SQLite concurrency hotfix

0.8.6 fixes workspace SQLite lock contention and makes browser tabs independent views of backend-owned jobs.

Previously, `/api/ui-state` could repeatedly initialize schema/WAL, a GET performed `INSERT OR IGNORE`, and view-state PATCH used multiple connections. Under concurrent scans/journals this could raise `sqlite3.OperationalError: database is locked`.

Now:
- WAL/schema initialization happens once per process/database;
- workspace GET is a pure read;
- workspace PATCH uses one connection/transaction;
- each browser tab has a persistent backend `view_id`;
- `workspace_views` stores tab-specific navigation/context;
- `workspace_state` remains the default inherited by a brand-new view;
- detached views never promote themselves to the default workspace;
- SSE workspace events are applied only to the matching `view_id`.

Commander and StreamCopy jobs remain backend-owned and survive UI navigation/refresh/close according to their existing journal/lease semantics.

For SFTP directory copies the UI now explicitly shows the synchronous remote-manifest preparation phase before the persistent Commander job is created.

The background storage watcher no longer runs a full expensive PowerShell disk inventory every few seconds; it emits a refresh trigger on root topology changes and leaves full inventory to the Disks view/fallback refresh.
