from __future__ import annotations

import argparse
import os
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.database import connect, init_database
from backend.scanner.classifier import classify_path


FILE_BATCH_SIZE = 2000
PROGRESS_FILE_INTERVAL = 250
SKIP_DIRECTORY_NAMES = {"system volume information"}

ProgressCallback = Callable[[dict[str, Any]], None]


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def scan(root: Path, progress_callback: ProgressCallback | None = None) -> int:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)

    init_database()
    connection = connect()
    scan_id: int | None = None
    files_count = 0
    directories_count = 0
    bytes_total = 0
    errors_count = 0

    try:
        cursor = connection.execute(
            "INSERT INTO scan_sessions (root_path, status) VALUES (?, 'running')",
            (str(root),),
        )
        scan_id = int(cursor.lastrowid)
        connection.commit()

        file_batch: list[tuple[Any, ...]] = []
        direct_sizes: dict[str, int] = defaultdict(int)
        direct_files: dict[str, int] = defaultdict(int)
        parents: dict[str, str | None] = {}
        directories: list[str] = []
        stack: list[Path] = [root]

        def report(current_path: str) -> None:
            if progress_callback is None:
                return
            progress_callback(
                {
                    "scan_id": scan_id,
                    "current_path": current_path,
                    "files": files_count,
                    "directories": directories_count,
                    "bytes": bytes_total,
                    "errors": errors_count,
                }
            )

        report(str(root))

        while stack:
            current = stack.pop()
            current_str = str(current)
            parent_str = None if current == root else str(current.parent)
            parents[current_str] = parent_str
            directories.append(current_str)
            child_directories = 0
            report(current_str)

            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            entry_path = Path(entry.path)
                            if _is_link_or_junction(entry_path):
                                continue

                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() in SKIP_DIRECTORY_NAMES:
                                    continue
                                child_directories += 1
                                stack.append(entry_path)
                                continue

                            if not entry.is_file(follow_symlinks=False):
                                continue

                            stat = entry.stat(follow_symlinks=False)
                            size = int(stat.st_size)
                            extension = entry_path.suffix.casefold() if entry_path.suffix else None
                            category = classify_path(entry_path, extension)

                            file_batch.append(
                                (
                                    scan_id,
                                    str(entry_path),
                                    current_str,
                                    entry.name,
                                    extension,
                                    category,
                                    size,
                                    int(stat.st_mtime_ns),
                                    int(stat.st_atime_ns),
                                    int(getattr(stat, "st_ctime_ns", 0)),
                                )
                            )
                            direct_sizes[current_str] += size
                            direct_files[current_str] += 1
                            files_count += 1
                            bytes_total += size

                            if files_count % PROGRESS_FILE_INTERVAL == 0:
                                report(current_str)
                            if len(file_batch) >= FILE_BATCH_SIZE:
                                _write_file_batch(connection, file_batch)
                                connection.commit()
                                file_batch.clear()

                        except (PermissionError, FileNotFoundError, OSError):
                            errors_count += 1

                connection.execute(
                    """
                    INSERT OR REPLACE INTO directories (
                        scan_id, path, parent_path, name, direct_size, direct_files,
                        child_directories, scan_complete
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        scan_id,
                        current_str,
                        parent_str,
                        current.name or current.drive,
                        direct_sizes[current_str],
                        direct_files[current_str],
                        child_directories,
                    ),
                )
                directories_count += 1
                report(current_str)
            except (PermissionError, FileNotFoundError, OSError) as exc:
                errors_count += 1
                print(f"[SKIP] {current}: {exc}")
                report(current_str)

        if file_batch:
            _write_file_batch(connection, file_batch)
            connection.commit()

        total_sizes = dict(direct_sizes)
        total_files = dict(direct_files)
        ordered = sorted(directories, key=lambda path: path.count(os.sep), reverse=True)
        for directory in ordered:
            parent = parents.get(directory)
            if parent is None:
                continue
            total_sizes[parent] = total_sizes.get(parent, 0) + total_sizes.get(directory, 0)
            total_files[parent] = total_files.get(parent, 0) + total_files.get(directory, 0)

        connection.executemany(
            """
            UPDATE directories SET total_size = ?, total_files = ?
            WHERE scan_id = ? AND path = ?
            """,
            [
                (total_sizes.get(path, 0), total_files.get(path, 0), scan_id, path)
                for path in directories
            ],
        )
        connection.execute(
            """
            UPDATE scan_sessions SET completed_at = CURRENT_TIMESTAMP, status = 'completed',
                files_count = ?, directories_count = ?, bytes_total = ?, errors_count = ?
            WHERE id = ?
            """,
            (files_count, directories_count, bytes_total, errors_count, scan_id),
        )
        connection.commit()
        report(str(root))

        print(f"Scan ID: {scan_id}")
        print(f"Root:    {root}")
        print("Completed")
        print(f"Files:       {files_count:,}")
        print(f"Directories: {directories_count:,}")
        print(f"Bytes:       {bytes_total:,}")
        print(f"Errors:      {errors_count:,}")
        return scan_id

    except (sqlite3.Error, OSError, ValueError):
        if scan_id is not None:
            _mark_scan_failed(connection, scan_id, files_count, directories_count, bytes_total, errors_count)
        raise
    finally:
        connection.close()


def _write_file_batch(connection: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO files (
            scan_id, path, parent_path, name, extension, category, size,
            modified_ns, accessed_ns, created_ns
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _mark_scan_failed(
    connection: sqlite3.Connection,
    scan_id: int,
    files_count: int,
    directories_count: int,
    bytes_total: int,
    errors_count: int,
) -> None:
    try:
        connection.execute(
            """
            UPDATE scan_sessions SET completed_at = CURRENT_TIMESTAMP, status = 'failed',
                files_count = ?, directories_count = ?, bytes_total = ?, errors_count = ?
            WHERE id = ?
            """,
            (files_count, directories_count, bytes_total, errors_count, scan_id),
        )
        connection.commit()
    except sqlite3.Error:
        return


def print_top_directories(scan_id: int, limit: int = 10) -> None:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT path, total_size, total_files FROM directories
            WHERE scan_id = ? ORDER BY total_size DESC LIMIT ?
            """,
            (scan_id, limit),
        ).fetchall()

    print("\nTOP directories")
    print("-" * 80)
    for row in rows:
        gib = row["total_size"] / (1024**3)
        mib = row["total_size"] / (1024**2)
        size_text = f"{gib:10.2f} GiB" if gib >= 1 else f"{mib:10.2f} MiB"
        print(f"{size_text} | {row['total_files']:8,d} files | {row['path']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="DiskShell Quick Indexer")
    parser.add_argument("path", type=Path)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()
    scan_id = scan(args.path)
    print_top_directories(scan_id, limit=args.top)


if __name__ == "__main__":
    main()
