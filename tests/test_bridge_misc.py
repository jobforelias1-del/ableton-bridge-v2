"""Tests for pitch helpers, note building, and lifecycle/context manager."""

from __future__ import annotations

from _fakes import default_song, make_bridge

from ableton_bridge import AbletonBridge, Note


def test_pitch_name_helpers_default_octave(bridge):
    assert bridge.pitch_to_name(60) == "C3"
    assert bridge.name_to_pitch("C3") == 60


def test_pitch_name_helpers_scientific_octave(fake):
    bridge = AbletonBridge(transport=fake, middle_c_octave=4)
    assert bridge.pitch_to_name(60) == "C4"
    assert bridge.name_to_pitch("C4") == 60


def test_make_note_from_int(bridge):
    note = bridge.make_note(60, 0.0, 1.0)
    assert note == Note(60, 0.0, 1.0, 100.0, False)


def test_make_note_from_name(bridge):
    note = bridge.make_note("C3", 0.5, 0.25, velocity=64, mute=True)
    assert note.pitch == 60
    assert note.start == 0.5
    assert note.velocity == 64.0
    assert note.mute is True


def test_make_note_respects_octave_convention(fake):
    bridge = AbletonBridge(transport=fake, middle_c_octave=4)
    assert bridge.make_note("C4", 0.0, 1.0).pitch == 60


def test_close_closes_transport(fake):
    bridge = make_bridge(fake)
    bridge.close()
    assert fake.closed is True


def test_context_manager_closes_transport():
    fake = default_song()
    with make_bridge(fake) as bridge:
        assert bridge.ping() is True
    assert fake.closed is True


def test_default_transport_is_osc_client():
    # Constructing without a transport binds a real OSCClient (ephemeral port to
    # avoid clashing with a real AbletonOSC on 11001).
    from ableton_bridge.osc_client import OSCClient

    bridge = AbletonBridge(receive_port=0)
    try:
        assert isinstance(bridge._osc, OSCClient)
    finally:
        bridge.close()
