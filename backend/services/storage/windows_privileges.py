from __future__ import annotations

import ctypes
import os


class WindowsElevationRequired(PermissionError):
    pass


def is_process_elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def require_process_elevated() -> None:
    if not is_process_elevated():
        raise WindowsElevationRequired(
            "Administrator privileges are required for Windows disk write operations"
        )
