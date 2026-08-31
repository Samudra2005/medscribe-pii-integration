"""span_types.py — the one shared type every detector produces."""

from dataclasses import dataclass


@dataclass
class Span:
    entity_type: str
    start: int
    end: int
    value: str
