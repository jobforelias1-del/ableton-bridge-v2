"""Tests for name resolution: tracks, scenes, has_midi_input, fire_scene."""

from __future__ import annotations

import pytest
from _fakes import FailingTransport, make_bridge

from ableton_bridge import (
    AbletonBridge,
    OSCTimeoutError,
    SceneNotFoundError,
    TrackNotFoundError,
)


def test_get_track_names(bridge):
    assert bridge.get_track_names() == ["K_piano", "S_808_clean", "Vocals"]


def test_get_track_names_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_track_names()


def test_get_track_index(bridge):
    assert bridge.get_track_index("S_808_clean") == 1


def test_get_track_index_not_found(bridge):
    with pytest.raises(TrackNotFoundError):
        bridge.get_track_index("does_not_exist")


def test_get_scene_names(bridge):
    assert bridge.get_scene_names() == ["Intro", "Verse", "Chorus"]


def test_get_scene_names_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_scene_names()


def test_get_scene_index(bridge):
    assert bridge.get_scene_index("Verse") == 1


def test_get_scene_index_not_found(bridge):
    with pytest.raises(SceneNotFoundError):
        bridge.get_scene_index("Bridge")


def test_fire_scene_by_name(fake):
    make_bridge(fake).fire_scene("Chorus")
    assert ("/live/scene/fire", (2,)) in fake.sent


def test_fire_scene_by_index(fake):
    make_bridge(fake).fire_scene(0)
    assert ("/live/scene/fire", (0,)) in fake.sent


def test_fire_scene_bad_name(bridge):
    with pytest.raises(SceneNotFoundError):
        bridge.fire_scene("Outro")


def test_track_has_midi_input_true(bridge):
    assert bridge.track_has_midi_input("K_piano") is True


def test_track_has_midi_input_false(bridge):
    assert bridge.track_has_midi_input("Vocals") is False


def test_track_has_midi_input_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).track_has_midi_input(0)
