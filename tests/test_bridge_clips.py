"""Tests for clip slot / clip operations: has_clip, create, delete, read."""

from __future__ import annotations

import pytest
from _fakes import FailingTransport, make_bridge

from ableton_bridge import (
    AbletonBridge,
    AudioTrackCannotHoldMidiError,
    ClipNotFoundError,
    Note,
    OSCTimeoutError,
    TrackNotFoundError,
)


def test_has_clip_false_then_true(fake):
    bridge = make_bridge(fake)
    assert bridge.has_clip("K_piano", 0) is False
    bridge.create_clip("K_piano", 0)
    assert bridge.has_clip("K_piano", 0) is True


def test_has_clip_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).has_clip(0, 0)


def test_create_clip_creates(fake):
    bridge = make_bridge(fake)
    assert bridge.create_clip("K_piano", 0, length=8.0) is True
    assert fake.tracks[0].clip_slots[0].length == 8.0


def test_create_clip_is_idempotent(fake):
    bridge = make_bridge(fake)
    assert bridge.create_clip("K_piano", 0) is True
    # Second call must be a no-op returning False, not an error.
    assert bridge.create_clip("K_piano", 0) is False
    creates = [s for s in fake.sent if s[0] == "/live/clip_slot/create_clip"]
    assert len(creates) == 1  # the second call did not re-send create


def test_create_clip_refuses_audio_track(bridge):
    with pytest.raises(AudioTrackCannotHoldMidiError):
        bridge.create_clip("Vocals", 0)


def test_create_clip_verify_failure_raises(fake):
    fake.create_clip_enabled = False  # simulate Live silently rejecting create
    bridge = make_bridge(fake)
    with pytest.raises(ClipNotFoundError):
        bridge.create_clip("K_piano", 1)


def test_create_clip_no_verify_skips_check(fake):
    fake.create_clip_enabled = False
    bridge = make_bridge(fake)
    # With verify disabled, no post-read happens, so no error is raised.
    assert bridge.create_clip("K_piano", 1, verify=False) is True


def test_delete_clip(fake):
    bridge = make_bridge(fake)
    bridge.create_clip("K_piano", 0)
    bridge.delete_clip("K_piano", 0)
    assert bridge.has_clip("K_piano", 0) is False


def test_delete_clip_bad_track_name(bridge):
    with pytest.raises(TrackNotFoundError):
        bridge.delete_clip("ghost", 0)


def test_read_clip(fake):
    bridge = make_bridge(fake)
    bridge.create_clip("K_piano", 0, length=4.0)
    bridge.add_notes("K_piano", 0, [Note.from_name("C3", 0.0, 1.0, velocity=90)])
    info = bridge.read_clip("K_piano", 0)
    assert info.track_index == 0
    assert info.length == 4.0
    assert info.time_signature == (4, 4)
    assert len(info.notes) == 1
    assert info.notes[0].name == "C3"
    assert info.notes[0].velocity == 90.0


def test_read_clip_missing_raises(bridge):
    with pytest.raises(ClipNotFoundError):
        bridge.read_clip("K_piano", 5)


def test_get_notes(fake):
    bridge = make_bridge(fake)
    bridge.create_clip("K_piano", 0)
    bridge.add_notes(
        "K_piano",
        0,
        [Note.from_name("C3", 0.0, 1.0), Note.from_name("E3", 1.0, 0.5)],
    )
    notes = bridge.get_notes("K_piano", 0)
    assert [n.name for n in notes] == ["C3", "E3"]


def test_get_notes_missing_raises(bridge):
    with pytest.raises(ClipNotFoundError):
        bridge.get_notes("K_piano", 9)
