# DiskShell 0.7.3 · backend-owned workspace state

DiskShell no longer treats the dashboard as a mandatory landing page. Navigation is local workspace state.

The backend persists the active page, active volume, and current scan id in `data/diskshell.db`. React reads `/api/ui-state` before rendering the workbench, so clearing browser cookies/site data, switching browsers on the same local DiskShell instance, or refreshing the page does not reset the workspace.

Browser localStorage remains only a fallback cache and is not the source of truth. No popup/window.open flow is used, so popup blockers do not affect workspace restoration.

When StreamCopy is active while another page is open, the header shows a `↩ StreamCopy · <status>` return chip. Reopening StreamCopy attaches to the backend-owned active job, or to the latest backend job when no active job remains.

This is intentionally a single local workspace with no account binding. The most recent navigation action from any browser becomes the current workspace state for that DiskShell instance.

Workspace state survives backend restart because it is stored in SQLite. StreamCopy 0.7.5 has its own persistent River Keeper: after backend restart a new worker claims an unfinished persistent job and resumes from a verified checkpoint. Commander remains a separate transfer manager with its own recovery model.
