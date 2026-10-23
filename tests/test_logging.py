from __future__ import annotations

import logging

from backend.core.logging_setup import configure_logging, log_event, log_warning


def test_logging_is_quiet_on_console_and_writes_rotating_journal(tmp_path):
    logger = configure_logging(tmp_path)

    assert logging.getLogger("werkzeug").disabled is True
    console_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
        and handler.__class__.__name__ == "StreamHandler"
    ]
    assert console_handlers
    assert all(handler.level >= logging.WARNING for handler in console_handlers)

    log_event("test.event", job_id="abc", status="running")
    log_warning("test.warning", job_id="abc", reason="example")
    for handler in logger.handlers:
        handler.flush()

    content = (tmp_path / "diskshell.log").read_text(encoding="utf-8")
    assert "test.event" in content
    assert "status='running'" in content
    assert "test.warning" in content


def test_log_fields_are_single_line(tmp_path):
    logger = configure_logging(tmp_path)
    log_event("test.event", detail="line1\nline2")
    for handler in logger.handlers:
        handler.flush()

    lines = (tmp_path / "diskshell.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "line1" in lines[0]
    assert "line2" in lines[0]
    assert "\\n" in lines[0]



def test_http_500_is_journaled_without_access_log(tmp_path):
    from backend.app import create_app

    logger = configure_logging(tmp_path)
    app = create_app()

    @app.get("/__test_500")
    def _test_500():
        return {"error": "synthetic"}, 500

    response = app.test_client().get("/__test_500")
    assert response.status_code == 500

    for handler in logger.handlers:
        handler.flush()

    content = (tmp_path / "diskshell.log").read_text(encoding="utf-8")
    assert "http.server_error" in content
    assert "/__test_500" in content
    assert '"GET /__test_500 HTTP/' not in content
