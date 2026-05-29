"""Tests for system/connection methods: ping, version, show_message."""

from __future__ import annotations

import pytest
from _fakes import FailingTransport, make_bridge

from ableton_bridge import AbletonBridge, OSCTimeoutError


def test_ping_ok(bridge):
    assert bridge.ping() is True


def test_ping_timeout():
    bridge = AbletonBridge(transport=FailingTransport())
    with pytest.raises(OSCTimeoutError):
        bridge.ping()


def test_get_live_version(bridge):
    assert bridge.get_live_version() == (12, 1)


def test_get_live_version_timeout():
    bridge = AbletonBridge(transport=FailingTransport())
    with pytest.raises(OSCTimeoutError):
        bridge.get_live_version()


def test_show_message(fake):
    bridge = make_bridge(fake)
    bridge.show_message("hello from the bridge")
    assert fake.messages == ["hello from the bridge"]


def test_show_message_transport_error():
    bridge = AbletonBridge(transport=FailingTransport())
    with pytest.raises(OSCTimeoutError):
        bridge.show_message("nope")
