# DiskShell 0.8.5 — HDD NTFS Locality Scheduler

StreamCopy adds an opt-in local source ordering mode:

```text
Manifest / directory order
NTFS first-LCN locality · EXP
```

The locality mode is available only for a **Local HDD source**.

After the normal manifest scan, DiskShell reads the first available NTFS LCN for each file through the Windows `FSCTL_GET_RETRIEVAL_POINTERS` control code and sorts the manifest by that value before handing it to the existing River Keeper copy engine.

This changes only source read ordering. It does not move extents, modify NTFS placement, bypass write gates, or enable `DS_ALLOW_EXTENT_MOVES`.

LCN is a logical NTFS cluster number, not exact platter/head geometry. HDD firmware still hides zoning, remapping, caches, read-ahead, command scheduling and physical angular geometry.

Fallback behavior is safe:
- files with known LCN are ordered ascending;
- unknown-LCN files remain stable at the end;
- if no LCN can be read, the effective order remains the original manifest order and a warning is recorded;
- SFTP always uses manifest order;
- SSD/Flash do not activate locality from the UI.

The feature remains opt-in until benchmark evidence shows it improves a specific HDD workload.
