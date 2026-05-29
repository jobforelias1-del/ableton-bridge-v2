"""Tests for pitch <-> name conversion and the Note dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ableton_bridge.notes import (
    MAX_PITCH,
    MIN_PITCH,
    Note,
    name_to_pitch,
    pitch_to_name,
)


class TestPitchToName:
    def test_middle_c_is_c3_by_default(self):
        assert pitch_to_name(60) == "C3"

    def test_sharps_and_octaves(self):
        assert pitch_to_name(61) == "C#3"
        assert pitch_to_name(72) == "C4"
        assert pitch_to_name(57) == "A2"

    def test_extremes(self):
        assert pitch_to_name(MIN_PITCH) == "C-2"
        assert pitch_to_name(MAX_PITCH) == "G8"

    def test_scientific_convention_is_opt_in(self):
        # With middle_c_octave=4, MIDI 60 is C4 (true scientific pitch notation).
        assert pitch_to_name(60, middle_c_octave=4) == "C4"

    @pytest.mark.parametrize("bad", [-1, 128, 200])
    def test_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            pitch_to_name(bad)


class TestNameToPitch:
    def test_middle_c(self):
        assert name_to_pitch("C3") == 60

    def test_case_insensitive_and_flats(self):
        assert name_to_pitch("c3") == 60
        assert name_to_pitch("Db3") == 61
        assert name_to_pitch("eb3") == name_to_pitch("D#3")

    def test_negative_octave(self):
        assert name_to_pitch("C-2") == 0

    def test_scientific_convention(self):
        assert name_to_pitch("C4", middle_c_octave=4) == 60

    @pytest.mark.parametrize("name", ["", "H3", "C", "Z#1", "C3.5", "##3"])
    def test_unparseable_raises(self, name):
        with pytest.raises(ValueError):
            name_to_pitch(name)

    def test_out_of_range_mapping_raises(self):
        with pytest.raises(ValueError):
            name_to_pitch("C9")  # above 127 under Ableton convention

    @pytest.mark.parametrize("midi", [0, 21, 60, 61, 100, 127])
    def test_round_trip(self, midi):
        assert name_to_pitch(pitch_to_name(midi)) == midi


class TestNote:
    def test_defaults(self):
        note = Note(60, 0.0, 1.0)
        assert note.velocity == 100.0
        assert note.mute is False

    def test_name_property(self):
        assert Note(60, 0.0, 1.0).name == "C3"

    def test_from_name(self):
        note = Note.from_name("C3", 0.0, 1.0, velocity=80, mute=True)
        assert note.pitch == 60
        assert note.velocity == 80
        assert note.mute is True

    def test_from_name_scientific(self):
        assert Note.from_name("C4", 0.0, 1.0, middle_c_octave=4).pitch == 60

    def test_key(self):
        assert Note(60, 2.5, 1.0).key() == (60, 2.5)

    def test_is_hashable_and_frozen(self):
        note = Note(60, 0.0, 1.0)
        assert note in {note}
        with pytest.raises(FrozenInstanceError):
            note.pitch = 61  # frozen
