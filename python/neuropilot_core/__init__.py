"""Minimal M0 Python package boundary."""

__version__ = "0.1.0"


def health() -> str:
    """Return a deterministic package health value for the M0 smoke test."""
    return "ok"
