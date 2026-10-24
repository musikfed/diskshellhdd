# DiskShell 0.8.4 — Local Subject / Object Search

## Что добавлено

Photos / People теперь умеет искать фотографии не только по лицам, но и по **локальным предметным/сюжетным тегам**.

Архитектура:

```text
Quick Index photo files
  -> optional local ONNX classifier
  -> top-K subject/object tags
  -> SQLite image_subject_tags
  -> instant tag search
```

### Важно: что это за модель

0.8.4 использует **whole-image classifier**, а не object detector с bounding boxes.

То есть фотография получает теги вроде:

- `sports car`
- `dog`
- `keyboard`
- `beach`

и после индексации поиск идёт по SQLite, без повторного запуска нейросети для каждого запроса.

## Настройка

Установить vision extras:

```powershell
uv sync --group dev --extra vision
```

В `.env`:

```text
DS_IMAGE_CLASSIFIER_MODEL=F:\models\classifier.onnx
DS_IMAGE_CLASSIFIER_LABELS=F:\models\labels.txt
DS_IMAGE_CLASSIFIER_INPUT_SIZE=224
```

Labels поддерживаются в форматах:

```text
cat
dog
sports car
```

или:

```text
0 cat
1 dog
2 sports car
```

или:

```text
0,cat
1,dog
2,sports car
```

или JSON array.

## Privacy

- inference локальный;
- cloud API не используется;
- модель и labels задаются локальными файлами;
- в SQLite хранятся derived tags и score.

## Ограничения

- classifier оценивает всё изображение целиком;
- bounding boxes / object localization пока не выполняются;
- качество поиска зависит от выбранной ONNX-модели и её label set;
- модель ожидается в формате NCHW float32 RGB с ImageNet normalization.
