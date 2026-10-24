# Failure / Recovery Validation

## Цель

Проверять не только happy path, а инварианты DiskShell:

- UI может исчезнуть без остановки durable job;
- backend process может исчезнуть без потери persistent StreamCopy state;
- другой physical volume не принимается за старый только из-за той же drive letter;
- непроверенный partial tail никогда не считается безопасным;
- source не удаляется до сильной проверки target.

## Автоматические тесты

CI покрывает:

- потерю RAM cache и чтение job из SQLite;
- recovery unfinished StreamCopy job;
- rollback повреждённого `.dspart` к подтверждённому checkpoint;
- COPY→SHA-256→DELETE SOURCE;
- lease/journal primitives;
- event fabric;
- current file catalog;
- workspace persistence;
- partition-boundary planner safety.

## Реальный Windows hardware checklist

Проводить только на тестовых данных с независимой резервной копией.

### Destination hot-unplug

1. SOURCE и DESTINATION — разные removable/local volumes.
2. Запусти StreamCopy COPY.
3. Дождись заметного прогресса/checkpoint на большом файле.
4. Отключи DESTINATION.
5. Job должна перейти в `waiting_endpoint`, а не в destructive cleanup.
6. Подключи **тот же physical volume**.
7. Убедись, что identity совпала, job → `recovering` → `running`.
8. После завершения сравни SHA-256 тестового набора.

### Wrong-volume test

1. Отключи DESTINATION.
2. Подключи другой накопитель, которому Windows дала ту же букву.
3. DiskShell не должен resume job на другом volume identity.
4. Подключи исходный volume и проверь нормальный resume.

### Backend kill / reboot

1. Запусти большой StreamCopy.
2. Принудительно заверши backend process или перезагрузи Windows.
3. Не удаляй `.dspart-<job>`.
4. Запусти backend снова.
5. После lease recovery job должна быть найдена в SQLite и получить новый worker.
6. Текущий файл должен продолжиться от последнего **проверенного** checkpoint, а не от произвольного EOF.

### Crash after publish / before delete

Для режима COPY→SHA-256→DELETE SOURCE:
1. source должен оставаться до publish+verify;
2. если process умер после target publish, recovery обязан перепроверить target;
3. source delete выполняется только после успешной повторной проверки.

## Что считать провалом

- silent overwrite готового destination target;
- resume на другом physical disk;
- удаление source при неполной/непроверенной копии;
- принятие случайного partial EOF как confirmed offset;
- две активные backend lease на одной job;
- потеря workspace/job только из-за закрытия браузера.
