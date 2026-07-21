"""Adapter registry. Each source module registers its fetch function on import (see
app/data/sources/__init__.py). One dedicated module per source — the isolation rule in
CLAUDE.md §5: a change to one source can never break another."""

_REGISTRY: dict[str, object] = {}


def register(name: str, adapter) -> None:
    _REGISTRY[name] = adapter


def get_adapter(name: str):
    return _REGISTRY.get(name)
