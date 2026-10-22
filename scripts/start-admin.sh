#!/usr/bin/env bash
set -euo pipefail

# RU: Повышаем права только для backend, а не для uv sync/npm build.
# EN: Elevate only the backend, not dependency installation or frontend builds.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo -E "${PROJECT_ROOT}/.venv/bin/python" -m backend.app
fi

exec "${PROJECT_ROOT}/.venv/bin/python" -m backend.app
