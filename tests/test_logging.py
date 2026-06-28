"""Logging configuration (0026): idempotency + level resolution."""

import logging

import pytest

from bbv2 import logging_setup


@pytest.fixture(autouse=True)
def _reset_logging():
    # Each test starts from a clean bbv2 logger + module-level guard.
    logging_setup._configured = False
    root = logging.getLogger("bbv2")
    root.handlers.clear()
    yield
    logging_setup._configured = False
    root.handlers.clear()


def test_configure_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("BBV2_LOG_DIR", str(tmp_path))
    logging_setup.configure_logging()
    n = len(logging.getLogger("bbv2").handlers)
    logging_setup.configure_logging()
    logging_setup.configure_logging(verbose=True)
    assert len(logging.getLogger("bbv2").handlers) == n  # no duplicate handlers


def test_verbose_sets_debug(monkeypatch, tmp_path):
    monkeypatch.setenv("BBV2_LOG_DIR", str(tmp_path))
    logging_setup.configure_logging(verbose=True)
    assert logging.getLogger("bbv2").level == logging.DEBUG


def test_explicit_level_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BBV2_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("BBV2_LOG_LEVEL", "WARNING")
    logging_setup.configure_logging(level="ERROR")
    assert logging.getLogger("bbv2").level == logging.ERROR


def test_env_level_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BBV2_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("BBV2_LOG_LEVEL", raising=False)
    logging_setup.configure_logging()
    assert logging.getLogger("bbv2").level == logging.INFO


def test_get_logger_namespaced():
    assert logging_setup.get_logger("collect").name == "bbv2.collect"


def test_emits_at_level(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("BBV2_LOG_DIR", str(tmp_path))
    logging_setup.configure_logging(level="INFO")
    with caplog.at_level(logging.INFO, logger="bbv2.test"):
        logging_setup.get_logger("test").info("hello %s", "world")
    assert any("hello world" in r.message for r in caplog.records)
