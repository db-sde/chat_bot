"""Failure guards and dependency health reporting."""

from .guards import guarded_call, with_fallback

__all__ = ["guarded_call", "with_fallback"]
