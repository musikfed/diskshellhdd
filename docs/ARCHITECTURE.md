# DiskShell architecture

DiskShell is organized around storage intent, not operating-system commands.

## Layers

1. **UI / Workspace** — React pages for disks, examination, analytics, placement plans, files, Vault and Storage Lab.
2. **Application API** — Flask blueprints. No shell strings are accepted from the browser.
3. **Storage Brain** — storage classes, placement rules, reserve policy and placement plans.
4. **Read-side engines** — scanner, analytics, previews, archive browser, optional vision, extent inspection.
5. **Write-side engines** — file copy/move/Trash, Vault writes, partition operations. Each domain has its own safety gate.
6. **Platform adapters** — Windows Storage PowerShell and Windows command-line adapters used only where required by the OS.

## Core principle

Read and write paths are separate. Newly connected drives can be examined and planned without enabling any write gate.

## Storage classes

Default classes are Incoming, Active, Media, Photos, Documents, Images/ISO, Archive, Backups, Development, Temporary, Vault, Quarantine and Other.

A placement plan is only a proposal. It records source path, target path, class, size and reason. Applying plans can be built on the safe file executor without changing the planner.

## Storage Lab

Storage Lab distinguishes logical placement from hidden HDD firmware geometry. Managed Interleave is represented as logical lanes and extents. The simulator can compare policy layouts before any future extent movement is enabled.

## Vault

Vault uses envelope encryption. Argon2id derives a key-encryption key from identity + secret. A random master key encrypts catalog and objects with AES-GCM. A separate recovery key wraps the same master key. Unlock state exists only in server memory and expires automatically.

## No Rust

All orchestration and current native integration are Python-based. Performance-critical work is delegated to the OS, SQLite, cryptographic/native libraries, Pillow/OpenCV/ONNX Runtime where enabled.
