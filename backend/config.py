from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("DS_HOST", "127.0.0.1")
    port: int = int(os.getenv("DS_PORT", "8765"))
    debug: bool = _env_bool("DS_DEBUG", True)

    allow_file_writes: bool = _env_bool("DS_ALLOW_FILE_WRITES", False)
    allow_vault_writes: bool = _env_bool("DS_ALLOW_VAULT_WRITES", False)
    allow_disk_writes: bool = _env_bool("DS_ALLOW_DISK_WRITES", False)
    allow_extent_moves: bool = _env_bool("DS_ALLOW_EXTENT_MOVES", False)

    soft_fill_limit: float = _env_float("DS_SOFT_FILL_LIMIT", 0.85)
    hard_fill_limit: float = _env_float("DS_HARD_FILL_LIMIT", 0.95)
    reserve_fraction: float = _env_float("DS_RESERVE_FRACTION", 0.05)

    vault_root_raw: str = os.getenv("DS_VAULT_ROOT", "")

    face_detector_model: str = os.getenv("DS_FACE_DETECTOR_MODEL", "")
    face_recognizer_model: str = os.getenv("DS_FACE_RECOGNIZER_MODEL", "")

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def vault_root(self) -> Path:
        if self.vault_root_raw:
            raw = Path(self.vault_root_raw)
            if not raw.is_absolute():
                raw = PROJECT_ROOT / raw
            return raw.resolve()
        return (self.data_dir / "vault").resolve()

    @property
    def data_dir(self) -> Path:
        raw = Path(os.getenv("DS_DATA_DIR", "./data"))
        if not raw.is_absolute():
            raw = PROJECT_ROOT / raw
        return raw.resolve()


settings = Settings()
