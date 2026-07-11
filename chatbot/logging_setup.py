"""Structured per-turn logging for the DegreeBaba chatbot.

Provides named loggers for each pipeline layer and configurable formatters for
local development (human-readable text) and production (JSON).  Every log line
for a ``/chat`` turn carries a short correlation id so a full turn trace can be
grepped out of a busy terminal.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Named loggers — one per pipeline layer so levels can be tuned independently.
LOGGERS = {
    "chatbot.nlu": logging.getLogger("chatbot.nlu"),
    "chatbot.resolver": logging.getLogger("chatbot.resolver"),
    "chatbot.routing": logging.getLogger("chatbot.routing"),
    "chatbot.leads": logging.getLogger("chatbot.leads"),
    "chatbot.llm": logging.getLogger("chatbot.llm"),
    "chatbot.catalog": logging.getLogger("chatbot.catalog"),
}


def correlation_id(session_id: str, turn: int) -> str:
    """Build a short, greppable correlation id for one turn."""

    prefix = session_id[-6:] if len(session_id) > 6 else session_id
    return f"sess_{prefix}:turn_{turn}"


class _TextFormatter(logging.Formatter):
    """Compact human-readable format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        cor = getattr(record, "cor", "")
        prefix = f"[{cor}] " if cor else ""
        level = record.levelname[0]
        return f"{prefix}{level} {record.name}: {record.getMessage()}"


class _JsonFormatter(logging.Formatter):
    """Structured JSON for production log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        cor = getattr(record, "cor", None)
        if cor:
            payload["cor"] = cor
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = str(record.exc_info[1])
        return json.dumps(payload, ensure_ascii=False)


def configure(
    *,
    level: str = "INFO",
    log_format: str = "text",
) -> None:
    """Set up the root logger and all named chatbot loggers."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = _JsonFormatter() if log_format.lower() == "json" else _TextFormatter()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Remove any pre-existing handlers (e.g. from basicConfig) to avoid dupes.
    root.handlers.clear()
    root.addHandler(handler)


class TurnLogger:
    """Convenience wrapper that injects the correlation id into every call."""

    def __init__(self, cor_id: str) -> None:
        self.cor = cor_id
        self._extra = {"cor": cor_id}

    def _logger(self, name: str) -> logging.Logger:
        return LOGGERS.get(name, logging.getLogger(name))

    def info(self, logger_name: str, msg: str, *args: object) -> None:
        self._logger(logger_name).info(msg, *args, extra=self._extra)

    def warning(self, logger_name: str, msg: str, *args: object) -> None:
        self._logger(logger_name).warning(msg, *args, extra=self._extra)

    def error(self, logger_name: str, msg: str, *args: object, **kwargs: object) -> None:
        self._logger(logger_name).error(msg, *args, extra=self._extra, **kwargs)


__all__ = ["LOGGERS", "TurnLogger", "configure", "correlation_id"]
