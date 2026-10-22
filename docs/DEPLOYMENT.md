# Deploying DiskShell 0.4 on Windows 11

Clone, copy `.env.example` to `.env`, run `uv sync --group dev`, Ruff, pytest, build the Vite frontend with Node 22+, then start `uv run python -m backend.app`. The default listener is `127.0.0.1:8765`.

Use `--extra preview` for PyMuPDF/7Z/ISO providers and `--extra vision` for local YuNet/SFace Photos/People. Configure model paths in `.env`.

Keep all `DS_ALLOW_*` gates at `0` for inspection. Enable each write domain only for the specific intended task. Never enable disk writes for the current Windows system/application disks. Extent moves remain disabled.

For upgrades from an existing local clone, back up `data`, fetch `origin`, hard-reset to `origin/main`, sync dependencies, rebuild the frontend, and run tests. SQLite schema migrations are applied automatically.

Keep `DS_HOST=127.0.0.1` until remote authentication is implemented for LAN/WireGuard deployment.
