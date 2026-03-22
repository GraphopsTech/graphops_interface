"""Resolve language names to analyzers via entry points. Grammar packages register under graphops_interface.grammars."""

import importlib.metadata
from typing import Any, List

GRAMMAR_GROUP = "graphops_interface.grammars"


def _entry_points_for_group(group: str) -> List[Any]:
    """Return entry points for group, supporting both Python 3.10 and 3.12+ APIs."""
    try:
        all_eps = importlib.metadata.entry_points()
    except Exception:
        return []
    if hasattr(all_eps, "select"):
        eps = all_eps.select(group=group)
    else:
        try:
            eps = importlib.metadata.entry_points(group=group)
        except TypeError:
            eps = getattr(all_eps, "get", lambda _: [])(group) or []
    return list(eps) if eps else []


def get_available_languages() -> List[str]:
    eps = _entry_points_for_group(GRAMMAR_GROUP)
    return sorted(set(ep.name for ep in eps))


def _is_valid_analyzer(obj: Any) -> bool:
    """True if obj has a callable analyze_directory (the contract for grammar plugins)."""
    return (
        obj is not None
        and hasattr(obj, "analyze_directory")
        and callable(getattr(obj, "analyze_directory"))
    )


def _load_analyzer_from_module(mod_name: str, attr: str = "get_analyzer") -> Any:
    """Load and call the analyzer factory from a module. Returns a valid analyzer or None."""
    try:
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, attr, None)
        if callable(fn):
            result = fn()
            return result if _is_valid_analyzer(result) else None
    except Exception:
        pass
    return None


def _load_analyzer_class(mod_name: str, class_name: str) -> Any:
    """Load a class from a module, instantiate it, return if valid analyzer else None."""
    try:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, class_name, None)
        if cls is not None and callable(cls):
            result = cls()
            return result if _is_valid_analyzer(result) else None
    except Exception:
        pass
    return None


def get_analyzer(language: str) -> Any:
    lang_key = (language or "").strip().replace("-", "_").lower()
    module_candidates = [
        lang_key,
        f"{lang_key}_grammers",
        lang_key.replace("_", "-"),
        f"{lang_key.replace('_', '-')}_grammers",
    ]

    # 1) Try entry points first
    eps = _entry_points_for_group(GRAMMAR_GROUP)
    ep = next((e for e in eps if (e.name or "").replace("-", "_").lower() == lang_key), None)
    if ep is not None:
        mod_name, _, attr = (ep.value or ":get_analyzer").partition(":")
        attr = attr or "get_analyzer"
        result = _load_analyzer_from_module(mod_name.strip(), attr)
        if result is not None:
            return result
        # Entry point pointed at a module that failed or returned non-analyzer; fall through

    # 2) Fallback: try direct module import (covers different venvs / entry point visibility)
    for mod_name in module_candidates:
        result = _load_analyzer_from_module(mod_name)
        if result is not None:
            return result

    available = get_available_languages()
    hint = f" Available: {', '.join(available)}" if available else ""
    raise ValueError(
        f"Grammar for '{language}' is not installed.{hint} "
        f"e.g.: pip install {lang_key.replace('_', '-')}-grammers"
    )
