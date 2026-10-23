from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from backend.config import settings


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def snapshot_state(destination: Path | None = None) -> Path:
    root = settings.project_root
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = destination or (settings.data_dir / "update-snapshots" / timestamp)
    target.mkdir(parents=True, exist_ok=False)

    db_source = settings.data_dir / "diskshell.db"
    db_target = target / "diskshell.db"
    if db_source.exists():
        source = sqlite3.connect(db_source)
        backup = sqlite3.connect(db_target)
        try:
            source.backup(backup)
        finally:
            backup.close()
            source.close()

    for source_path in (
        root / ".env",
        settings.data_dir / "vault-location.json",
    ):
        if source_path.exists() and source_path.is_file():
            shutil.copy2(source_path, target / source_path.name)

    manifest = {
        "created_at": datetime.now().isoformat(),
        "git_commit": _git_commit(root),
        "project_root": str(root),
        "data_dir": str(settings.data_dir),
        "database": str(db_target) if db_target.exists() else None,
        "note": (
            "State snapshot for DiskShell runtime update. StreamCopy .dspart data stays "
            "on transfer target volumes and is not copied into this snapshot."
        ),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(snapshot_state(args.destination))


if __name__ == "__main__":
    main()
