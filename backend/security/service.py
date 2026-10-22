from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _defender_path() -> Path | None:
    program_data = Path(os.getenv("ProgramData", r"C:\ProgramData"))
    platform = program_data / "Microsoft" / "Windows Defender" / "Platform"
    if platform.exists():
        candidates = sorted(
            (p / "MpCmdRun.exe" for p in platform.iterdir() if p.is_dir()),
            reverse=True,
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate

    program_files = Path(os.getenv("ProgramFiles", r"C:\Program Files"))
    fallback = program_files / "Windows Defender" / "MpCmdRun.exe"
    if fallback.exists():
        return fallback

    found = shutil.which("MpCmdRun.exe")
    return Path(found) if found else None


def available_engines() -> list[dict[str, Any]]:
    defender = _defender_path()
    clam = shutil.which("clamscan")
    return [
        {
            "id": "defender",
            "title": "Microsoft Defender",
            "available": defender is not None,
            "path": str(defender) if defender else None,
            "remediation": False,
            "local_only": True,
        },
        {
            "id": "clamav",
            "title": "ClamAV",
            "available": clam is not None,
            "path": clam,
            "remediation": False,
            "local_only": True,
        },
    ]


def choose_engine(requested: str = "auto") -> dict[str, Any]:
    engines = available_engines()
    available = {engine["id"]: engine for engine in engines if engine["available"]}
    if requested == "auto":
        for engine_id in ("defender", "clamav"):
            if engine_id in available:
                return available[engine_id]
        raise RuntimeError("No supported local malware scanner is available")
    if requested not in available:
        raise RuntimeError(f"Security engine '{requested}' is not available")
    return available[requested]


def build_scan_command(engine: dict[str, Any], path: Path) -> list[str]:
    if engine["id"] == "defender":
        return [
            str(engine["path"]),
            "-Scan",
            "-ScanType",
            "3",
            "-File",
            str(path),
            "-DisableRemediation",
        ]
    if engine["id"] == "clamav":
        return [
            str(engine["path"]),
            "--recursive",
            "--infected",
            "--no-summary",
            str(path),
        ]
    raise RuntimeError("Unsupported security engine")
