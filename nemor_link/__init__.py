"""Compatibility namespace for the former :mod:`nemor_link` package."""

import importlib
import sys
import warnings


warnings.warn(
    "'nemor_link' was renamed to 'inference_link'; update imports to the new name",
    DeprecationWarning,
    stacklevel=2,
)

_canonical = importlib.import_module("inference_link")
__all__ = list(_canonical.__all__)

for _name in __all__:
    globals()[_name] = getattr(_canonical, _name)

_SUBMODULES = (
    "base",
    "cli",
    "config",
    "connection",
    "llm",
    "pool",
    "runner",
    "state",
    "stt",
    "tls",
    "tts",
)

for _name in _SUBMODULES:
    _module = importlib.import_module(f"inference_link.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    if _name not in {"llm", "stt", "tts"}:
        globals()[_name] = _module


def __getattr__(name):
    return getattr(_canonical, name)
