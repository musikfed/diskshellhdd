# DiskShell 0.8.3 — Remote River / SFTP

Remote River extends the existing persistent StreamCopy journal instead of introducing another transfer system.

Supported routes:

- Local → SFTP
- SFTP → Local
- SFTP → SFTP
- Local → Local continues to use the StreamCopy v2 microfile worker.

Remote credentials are never persisted. The journal stores only endpoint metadata and a stable identity:

```text
protocol|host|port|username|root
```

After backend restart the old RAM connection id may be invalid. The job remains in `waiting_endpoint` until the user recreates a matching SFTP profile, then rebinds automatically by stable identity.

Remote River uses the same SHA-256 checkpoint model as local River Keeper. Recovery validates source and partial checkpoint ranges, truncates any unverified tail, and resumes from the last confirmed offset.

Files are written to `.dspart-<job>`, verified, then published by rename. COPY→SHA-256→DELETE SOURCE removes the source only after strong verification.

FTP/FTPS are intentionally excluded from Remote River 0.8.3 because safe checkpoint rollback requires predictable truncate/resume semantics. SFTP provides the required stat/read/write/rename/truncate model.

Remote microfile batching is not enabled yet; 0.8.3 prioritizes restart and endpoint-reconnect safety.
