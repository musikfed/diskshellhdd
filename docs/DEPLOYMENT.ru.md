# Инструкция по развёртыванию

Эта инструкция описывает запуск DiskShell baseline 0.2 на Windows 11.

## 1. Требования

Установи Windows 11, Git, uv и Python 3.12.

Проверка:

    git --version
    uv --version

## 2. Клонирование

    git clone https://github.com/musikfed/diskshellhdd.git
    cd diskshellhdd

## 3. Python-окружение

DiskShell baseline 0.2 рассчитан на Python 3.12.

    uv sync
    uv run python --version

Ожидается Python 3.12.x.

## 4. Конфигурация

    Copy-Item .env.example .env

Рекомендуемые значения:

    DS_HOST=127.0.0.1
    DS_PORT=8765
    DS_DEBUG=1
    DS_DATA_DIR=./data
    DS_ALLOW_DESTRUCTIVE=0

Для baseline 0.2 destructive operations включать нельзя.

## 5. Проверка Ruff

    uv run ruff check backend tests

Для безопасного автоматического исправления lint/import-ошибок:

    uv run ruff check backend tests --fix

После этого снова выполнить обычную проверку.

## 6. Тесты

    uv run pytest -v

## 7. Запуск backend

    uv run python -m backend.app

Локальный адрес: http://127.0.0.1:8765

Основные endpoints:

- GET /
- GET /api/health
- GET /api/disks
- POST /api/scans
- GET /api/scans/<job_id>
- GET /api/index/scans/<scan_id>/top
- GET /api/index/scans/<scan_id>/directory

## 8. Проверка CLI-сканера

Сначала используй небольшой каталог:

    uv run python -m backend.scanner.quick_scan F:\\diskshellhdd\\backend

Сканируемый каталог DiskShell не изменяет. Индекс записывается только в собственную SQLite-базу приложения.

## 9. Проверка фонового сканирования

Оставь Flask работающим в одном окне PowerShell. Во втором:

    $body = @{ path = "F:\\diskshellhdd\\backend" } | ConvertTo-Json
    $result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/scans" -ContentType "application/json" -Body $body
    $job = $result.id
    Invoke-RestMethod "http://127.0.0.1:8765/api/scans/$job" | Format-List

Успешная задача должна показать status = completed, ненулевые счётчики files/directories и scan_id.

## 10. Безопасность дисков

В baseline 0.2 нельзя добавлять или вызывать Clear-Disk, Initialize-Disk, Format-Volume, разрушительные команды diskpart, raw disk writes или перемещение экстентов.

Для всех физических дисков должен оставаться write_policy = blocked.

## 11. Flask development server

Встроенный Flask server используется только для локальной разработки. Для будущего LAN/WireGuard развёртывания нужен production WSGI (например Waitress), аутентификация и firewall restrictions. До этого сервис остаётся на 127.0.0.1.

## 12. Где хранится база

По умолчанию:

    data\\diskshell.db

В будущем базу приложения, cache, thumbnails и временные файлы лучше держать на SSD/NVMe, а не на основном storage HDD.

## 13. Правило дальнейшей разработки

Перед крупным изменением:

    git status
    git add .
    git commit -m "checkpoint: working baseline"

Дальше добавляем по одному milestone и не смешиваем read-side функции с потенциально опасными write-side операциями.
