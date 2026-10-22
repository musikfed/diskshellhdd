# DiskShell 0.4 architecture

DiskShell is layered as UI → application API → Storage Brain/content services → safe executors → filesystem/Windows adapters. PowerShell is only a Windows adapter, not the product model.

The read side contains disk discovery, indexing, analytics, previews, archive/ISO browsing, duplicate analysis, local Photos/People, NTFS extent queries and benchmarks. Write domains are independently gated: files, Vault, disk/partition writes and future extent moves.

The Placement Executor distinguishes same-volume atomic moves from cross-volume verified copies. Cross-volume originals are intentionally retained after verification. Same-volume operations are journalled and can be rolled back.

Storage Classes are logical policy zones, not fixed partitions. Capacity policy keeps a working-space reserve and soft/hard fill limits.

Vault uses Argon2id envelope encryption and chunked AES-256-GCM objects. Local Photos/People uses optional YuNet/SFace models with no cloud dependency.

Storage Lab models logical Managed Interleave and filesystem extents only; HDD firmware physical geometry remains outside application control. Actual extent relocation remains locked pending target-hardware benchmarks.
