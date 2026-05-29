"""Tests for note write operations: add_notes, remove_notes, modify_notes."""

from __future__ import annotations

import pytest
from _fakes import make_bridge

from ableton_bridge import AudioTrackCannotHoldMidiError, ClipNotFoundError, Note


@pytest.fixture
def piano_clip(fake):
    """A bridge with an empty clip ready at track 'K_piano', slot 0."""
    bridge = make_bridge(fake)
    bridge.create_clip("K_piano", 0, length=4.0)
    return bridge, fake


def test_add_notes_is_batched_single_message(piano_clip):
    bridge, fake = piano_clip
    notes = [
        Note.from_name("C3", 0.0, 1.0),
        Note.from_name("E3", 1.0, 1.0),
        Note.from_name("G3", 2.0, 1.0),
    ]
    fake.sent.clear()
    bridge.add_notes("K_piano", 0, notes)
    adds = [s for s in fake.sent if s[0] == "/live/clip/add/notes"]
    assert len(adds) == 1  # all notes in a single OSC message
    # 2 leading indices + 3 notes * 5 fields.
    assert len(adds[0][1]) == 2 + 3 * 5
    assert len(fake.tracks[0].clip_slots[0].notes) == 3


def test_add_notes_empty_is_noop(piano_clip):
    bridge, fake = piano_clip
    fake.sent.clear()
    bridge.add_notes("K_piano", 0, [])
    assert not any(s[0] == "/live/clip/add/notes" for s in fake.sent)


def test_add_notes_refuses_audio_track(bridge):
    with pytest.raises(AudioTrackCannotHoldMidiError):
        bridge.add_notes("Vocals", 0, [Note(60, 0.0, 1.0)])


def test_add_notes_without_clip_raises(bridge):
    with pytest.raises(ClipNotFoundError):
        bridge.add_notes("K_piano", 7, [Note(60, 0.0, 1.0)])


def test_remove_single_note_uses_send_not_bundle(piano_clip):
    bridge, fake = piano_clip
    bridge.add_notes(
        "K_piano",
        0,
        [Note.from_name("C3", 0.0, 1.0), Note.from_name("D3", 0.0, 1.0)],
    )
    fake.bundles.clear()
    bridge.remove_notes("K_piano", 0, [(60, 0.0)])  # remove C3 only
    assert fake.bundles == []  # single removal goes via send, not a bundle
    remaining = [n[0] for n in fake.tracks[0].clip_slots[0].notes]
    assert remaining == [62]  # only D3 (62) remains


def test_remove_multiple_notes_uses_bundle(piano_clip):
    bridge, fake = piano_clip
    bridge.add_notes(
        "K_piano",
        0,
        [
            Note.from_name("C3", 0.0, 1.0),
            Note.from_name("D3", 1.0, 1.0),
            Note.from_name("E3", 2.0, 1.0),
        ],
    )
    bridge.remove_notes("K_piano", 0, [(60, 0.0), Note.from_name("E3", 2.0, 1.0)])
    assert len(fake.bundles) == 1
    assert len(fake.bundles[0]) == 2  # two remove messages in the bundle
    remaining = [n[0] for n in fake.tracks[0].clip_slots[0].notes]
    assert remaining == [62]  # only D3 remains


def test_remove_notes_by_name_key(piano_clip):
    bridge, fake = piano_clip
    bridge.add_notes(
        "K_piano",
        0,
        [Note.from_name("C3", 0.0, 1.0), Note.from_name("D3", 0.0, 1.0)],
    )
    # Keys may use a scientific-notation pitch name instead of a MIDI int.
    bridge.remove_notes("K_piano", 0, [("C3", 0.0)])
    remaining = [n[0] for n in fake.tracks[0].clip_slots[0].notes]
    assert remaining == [62]  # only D3 remains


def test_remove_notes_empty_is_noop(piano_clip):
    bridge, fake = piano_clip
    fake.sent.clear()
    bridge.remove_notes("K_piano", 0, [])
    assert not any("remove/notes" in s[0] for s in fake.sent)


def test_remove_notes_refuses_audio_track(bridge):
    with pytest.raises(AudioTrackCannotHoldMidiError):
        bridge.remove_notes("Vocals", 0, [(60, 0.0)])


def test_remove_notes_without_clip_raises(bridge):
    with pytest.raises(ClipNotFoundError):
        bridge.remove_notes("K_piano", 7, [(60, 0.0)])


def test_modify_notes_remove_then_add_in_one_bundle(piano_clip):
    bridge, fake = piano_clip
    bridge.add_notes("K_piano", 0, [Note.from_name("C3", 0.0, 1.0, velocity=100)])
    bridge.modify_notes(
        "K_piano",
        0,
        [((60, 0.0), Note.from_name("G3", 0.0, 1.0, velocity=80))],
    )
    # One bundle: remove(s) first, the single batched add last.
    assert len(fake.bundles) == 1
    bundle = fake.bundles[0]
    addresses = [address for address, _ in bundle]
    assert addresses[-1] == "/live/clip/add/notes"
    assert all(a == "/live/clip/remove/notes" for a in addresses[:-1])
    # End state: C3 replaced by G3 at velocity 80.
    notes = fake.tracks[0].clip_slots[0].notes
    assert len(notes) == 1
    assert notes[0][0] == 67  # G3
    assert notes[0][3] == 80.0


def test_modify_multiple_notes(piano_clip):
    bridge, fake = piano_clip
    bridge.add_notes(
        "K_piano",
        0,
        [
            Note.from_name("C3", 0.0, 1.0),
            Note.from_name("D3", 1.0, 1.0),
            Note.from_name("E3", 2.0, 1.0),
        ],
    )
    bridge.modify_notes(
        "K_piano",
        0,
        [
            ((60, 0.0), Note.from_name("C4", 0.0, 1.0)),
            (Note.from_name("E3", 2.0, 1.0), Note.from_name("F3", 2.0, 1.0)),
        ],
    )
    bundle = fake.bundles[0]
    # Two removes + one batched add.
    assert [a for a, _ in bundle].count("/live/clip/remove/notes") == 2
    assert [a for a, _ in bundle].count("/live/clip/add/notes") == 1
    pitches = sorted(n[0] for n in fake.tracks[0].clip_slots[0].notes)
    assert pitches == [62, 65, 72]  # D3 untouched, E3->F3, C3->C4


def test_modify_notes_empty_is_noop(piano_clip):
    bridge, fake = piano_clip
    bridge.modify_notes("K_piano", 0, [])
    assert fake.bundles == []


def test_modify_notes_refuses_audio_track(bridge):
    with pytest.raises(AudioTrackCannotHoldMidiError):
        bridge.modify_notes("Vocals", 0, [((60, 0.0), Note(62, 0.0, 1.0))])


def test_modify_notes_without_clip_raises(bridge):
    with pytest.raises(ClipNotFoundError):
        bridge.modify_notes("K_piano", 7, [((60, 0.0), Note(62, 0.0, 1.0))])
