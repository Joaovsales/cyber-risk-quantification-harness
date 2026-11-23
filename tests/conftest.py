"""Fixtures shared across the test folders."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml


@dataclass
class DocumentIO:
    """Per file name, how often a file is read from disk and how often the text read is parsed."""

    reads: Counter = field(default_factory=Counter)
    parses: Counter = field(default_factory=Counter)


@pytest.fixture
def document_io(monkeypatch) -> DocumentIO:
    """Counts reads (``Path.read_bytes`` / ``read_text``) and YAML parses (``yaml.load``) per file name.

    Parses are counted where every YAML parse ends: ``yaml.load``, which ``parse_yaml`` calls and
    ``yaml.safe_load`` calls too, so a new caller of either is counted wherever it imported it from.
    """
    counts = DocumentIO()
    real_read_bytes, real_read_text, real_load = Path.read_bytes, Path.read_text, yaml.load
    read_from: dict[str, str] = {}

    def remember(path: Path, text: str) -> None:
        counts.reads[path.name] += 1
        read_from[text] = path.name

    def read_bytes(path: Path) -> bytes:
        data = real_read_bytes(path)
        remember(path, data.decode("utf-8", errors="replace"))
        return data

    def read_text(path: Path, *args, **kwargs) -> str:
        text = real_read_text(path, *args, **kwargs)
        remember(path, text)
        return text

    def load(stream, Loader):  # noqa: N803 - yaml.load's own parameter name
        if isinstance(stream, str) and stream in read_from:
            counts.parses[read_from[stream]] += 1
        return real_load(stream, Loader)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(yaml, "load", load)
    return counts
