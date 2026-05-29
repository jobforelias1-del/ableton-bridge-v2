"""Tests for song/transport methods: tempo, playback, time signature."""

from __future__ import annotations

import pytest
from _fakes import FailingTransport, make_bridge

from ableton_bridge import AbletonBridge, OSCTimeoutError


def test_get_tempo(bridge):
    assert bridge.get_tempo() == 120.0


def test_get_tempo_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_tempo()


def test_set_tempo(fake):
    make_bridge(fake).set_tempo(128.5)
    assert fake.tempo == 128.5
    assert ("/live/song/set/tempo", (128.5,)) in fake.sent


def test_set_tempo_transport_error():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).set_tempo(120)


def test_is_playing(fake):
    fake.is_playing = True
    assert make_bridge(fake).is_playing() is True


def test_is_playing_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).is_playing()


def test_start_playing(fake):
    make_bridge(fake).start_playing()
    assert fake.is_playing is True


def test_stop_playing(fake):
    fake.is_playing = True
    make_bridge(fake).stop_playing()
    assert fake.is_playing is False


def test_continue_playing(fake):
    make_bridge(fake).continue_playing()
    assert fake.is_playing is True


@pytest.mark.parametrize("method", ["start_playing", "stop_playing", "continue_playing"])
def test_transport_methods_transport_error(method):
    bridge = AbletonBridge(transport=FailingTransport())
    with pytest.raises(OSCTimeoutError):
        getattr(bridge, method)()


def test_get_time_signature(bridge):
    assert bridge.get_time_signature() == (4, 4)


def test_get_time_signature_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_time_signature()


def test_set_time_signature(fake):
    make_bridge(fake).set_time_signature(3, 8)
    assert fake.signature == [3, 8]


def test_set_time_signature_transport_error():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).set_time_signature(7, 8)
