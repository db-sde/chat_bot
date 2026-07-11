"""Reusable boundaries that keep external failures out of the request path."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import Awaitable, Callable

LOGGER = logging.getLogger(__name__)


async def _materialize[T](value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


async def guarded_call[T](
    operation: Callable[[], T | Awaitable[T]],
    fallback: Callable[[], T | Awaitable[T]] | T,
    *,
    timeout: float,
    label: str = "external operation",
) -> T:
    """Run an operation with an explicit deadline and materialize a safe fallback."""

    try:
        result = operation()
        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, timeout=timeout)
        return result
    except Exception as exc:
        LOGGER.warning("%s failed; using fallback: %s", label, exc)
        fallback_value = fallback() if callable(fallback) else fallback
        return await _materialize(fallback_value)


def with_fallback[**P, T](
    fallback: Callable[P, T | Awaitable[T]],
    *,
    timeout: float,
    label: str | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorate an async boundary so it resolves to the supplied fallback."""

    def decorator(function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            async def run() -> T:
                return await function(*args, **kwargs)

            async def recover() -> T:
                return await _materialize(fallback(*args, **kwargs))

            return await guarded_call(
                run,
                recover,
                timeout=timeout,
                label=label or function.__qualname__,
            )

        return wrapped

    return decorator
