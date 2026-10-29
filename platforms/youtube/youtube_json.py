"""Compatibility import; all stores now use the common persistence helper."""

from persistence import atomic_write_json

__all__ = ["atomic_write_json"]
