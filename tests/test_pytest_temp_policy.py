from __future__ import annotations

from pathlib import Path


def test_pytest_tmp_path_stays_inside_project(tmp_path: Path) -> None:
    project_temp = (Path.cwd() / ".pytest-tmp").resolve()
    resolved = tmp_path.resolve()

    assert resolved.is_relative_to(project_temp)
