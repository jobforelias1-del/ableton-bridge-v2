"""Pytest fixtures wiring the bridge to the in-memory AbletonOSC fake."""

from __future__ import annotations

import pytest
from _fakes import FakeAbleton, default_song, make_bridge

# Re-export so test modules can ``from _fakes import ...`` or use fixtures.
__all__ = ["FakeAbleton", "default_song", "make_bridge"]


@pytest.fixture
def fake() -> FakeAbleton:
    """A default song with MIDI and audio tracks and a macro rack."""
    return default_song()


@pytest.fixture
def bridge(fake: FakeAbleton):
    """A bridge wired to the default :func:`fake` song."""
    return make_bridge(fake)
