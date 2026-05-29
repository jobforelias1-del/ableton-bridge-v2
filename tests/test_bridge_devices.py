"""Tests for device parameters (rack macros) and track sends."""

from __future__ import annotations

import pytest
from _fakes import FailingTransport, make_bridge

from ableton_bridge import (
    AbletonBridge,
    DeviceNotFoundError,
    OSCTimeoutError,
    ParameterNotFoundError,
)


def test_get_device_names(bridge):
    assert bridge.get_device_names("K_piano") == ["K_piano"]


def test_get_device_names_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_device_names(0)


def test_get_device_index(bridge):
    assert bridge.get_device_index("K_piano", "K_piano") == 0


def test_get_device_index_not_found(bridge):
    with pytest.raises(DeviceNotFoundError):
        bridge.get_device_index("K_piano", "Reverb")


def test_get_parameter_names(bridge):
    assert bridge.get_parameter_names("K_piano", 0) == ["Macro 1", "Macro 2", "Volume"]


def test_get_parameter_names_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_parameter_names(0, 0)


def test_get_parameter_index(bridge):
    assert bridge.get_parameter_index("K_piano", "K_piano", "Macro 2") == 1


def test_get_parameter_index_not_found(bridge):
    with pytest.raises(ParameterNotFoundError):
        bridge.get_parameter_index("K_piano", 0, "Macro 9")


def test_get_parameter_value_by_index(bridge):
    assert bridge.get_parameter_value("K_piano", 0, 1) == 0.5


def test_get_parameter_value_by_name(bridge):
    assert bridge.get_parameter_value("K_piano", "K_piano", "Macro 1") == 0.0


def test_get_parameter_value_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_parameter_value(0, 0, 0)


def test_set_parameter_value_by_name(fake):
    bridge = make_bridge(fake)
    bridge.set_parameter_value("K_piano", "K_piano", "Macro 1", 0.75)
    assert fake.tracks[0].devices[0].parameters[0][1] == 0.75


def test_set_parameter_value_unknown_parameter(bridge):
    with pytest.raises(ParameterNotFoundError):
        bridge.set_parameter_value("K_piano", 0, "Macro 42", 0.5)


def test_get_send(bridge):
    assert bridge.get_send("K_piano", 0) == 0.0


def test_get_send_timeout():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).get_send(0, 0)


def test_set_send(fake):
    bridge = make_bridge(fake)
    bridge.set_send("S_808_clean", 1, 0.3)
    assert fake.tracks[1].sends[1] == 0.3


def test_set_send_transport_error():
    with pytest.raises(OSCTimeoutError):
        AbletonBridge(transport=FailingTransport()).set_send(0, 0, 0.5)
