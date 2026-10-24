# DiskShell 0.8.4 — Local Subject / Object Search

Photos / People can now search images by local subject/object tags in addition to face/person similarity.

Architecture:

```text
Quick Index photo files
  -> optional local ONNX classifier
  -> top-K subject/object tags
  -> SQLite image_subject_tags
  -> instant tag search
```

0.8.4 deliberately implements **whole-image classification**, not bounding-box object detection. Typical tags are `sports car`, `dog`, `keyboard`, or `beach`. Once indexed, searches use SQLite and do not rerun inference for every query.

Install the vision extras:

```powershell
uv sync --group dev --extra vision
```

Configure:

```text
DS_IMAGE_CLASSIFIER_MODEL=F:\models\classifier.onnx
DS_IMAGE_CLASSIFIER_LABELS=F:\models\labels.txt
DS_IMAGE_CLASSIFIER_INPUT_SIZE=224
```

Labels may be plain one-per-line, prefixed by numeric indices, comma-separated index/label rows, or a JSON string array.

Privacy:
- inference is local;
- no cloud API is used;
- model/labels are local files;
- only derived tags and scores are stored in SQLite.

Limitations:
- classification covers the whole image;
- no bounding-box localization yet;
- quality depends on the selected ONNX classifier and label vocabulary;
- the model is expected to accept NCHW float32 RGB with ImageNet normalization.
