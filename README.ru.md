# DiskShell HDD

Русский · [English](README.md)

DiskShell — локальный проект для безопасного обследования, индексирования и последующей аналитики накопителей в Windows. Текущий baseline сосредоточен на read-only обнаружении физических дисков и томов, быстром индексировании файловой системы, истории сканирований в SQLite и локальном Flask API.

## Текущий baseline: 0.2

Уже реализовано:

- обнаружение физических дисков, разделов и томов Windows 11;
- read-only запросы через PowerShell Storage;
- автоматические признаки защиты для system / boot / application disk;
- локальный SQLite-индекс DiskShell;
- Quick Indexer на базе os.scandir;
- bottom-up подсчёт размеров каталогов;
- фоновые scan jobs с живыми счётчиками;
- Flask API, по умолчанию доступный только на localhost;
- проверки Ruff и pytest.

Планируется далее:

- Analytics и классификация файлов;
- React-интерфейс;
- preview providers для изображений, документов, архивов, ISO и медиа;
- локальное распознавание людей на фотографиях;
- файловый менеджер с quarantine-first логикой;
- Vault;
- Partition Magic с отдельным привилегированным safety layer;
- экспериментальный Storage Lab / managed layout.

## Модель безопасности

Baseline 0.2 намеренно не выполняет разрушительных операций.

На этом этапе DiskShell не инициализирует, не форматирует, не очищает и не переразмечает диски, не удаляет пользовательские данные и не перемещает экстенты. Для каждого физического диска API возвращает write_policy = blocked.

Сканирование файловой системы только читает метаданные выбранного каталога. Результаты записываются только в собственную локальную SQLite-базу DiskShell.

## Требования

- Windows 11
- Python 3.12
- uv
- PowerShell с Windows Storage module

## Быстрый запуск

    git clone https://github.com/musikfed/diskshellhdd.git
    cd diskshellhdd
    Copy-Item .env.example .env
    uv sync
    uv run ruff check backend tests
    uv run pytest -v
    uv run python -m backend.app

Открыть в браузере:

- http://127.0.0.1:8765/
- http://127.0.0.1:8765/api/health
- http://127.0.0.1:8765/api/disks

Полная инструкция развёртывания на русском: [docs/DEPLOYMENT.ru.md](docs/DEPLOYMENT.ru.md)

English deployment guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## Текущий статус разработки

Рабочий baseline уже проверен локально: background scan job успешно завершает индексирование без ошибок сканера. Следующий milestone — классификация файлов и Analytics API.

## Лицензия

Лицензия пока не выбрана.
