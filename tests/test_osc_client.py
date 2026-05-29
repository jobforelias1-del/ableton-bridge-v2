"""Tests for the low-level OSCClient against a real loopback UDP server.

A small threaded :class:`FakeServer` plays the role of AbletonOSC: it receives
messages and, per address, sends back a configured list of replies. Reply specs
may be raw bytes (to exercise the malformed-datagram path) or ``(address,
params)`` pairs (to exercise address/leading-arg matching).
"""

from __future__ import annotations

import socket
import threading

import pytest
from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from ableton_bridge.exceptions import OSCTimeoutError
from ableton_bridge.osc_client import OSCClient


def _encode(address, params):
    builder = OscMessageBuilder(address)
    for param in params:
        builder.add_arg(param)
    return builder.build().dgram


class FakeServer:
    """A threaded loopback UDP server that mimics AbletonOSC replies."""

    def __init__(self, responses=None):
        # address -> list of reply specs (bytes, or (reply_address, params)).
        self.responses = responses or {}
        self.received = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        self.sock.settimeout(0.1)
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65536)
            except TimeoutError:
                continue
            except OSError:
                break
            self._handle(data, addr)

    def _handle(self, data, addr):
        if OscBundle.dgram_is_bundle(data):
            for item in OscBundle(data):
                self._handle(item.dgram, addr)
            return
        message = OscMessage(data)
        self.received.append((message.address, list(message.params)))
        for spec in self.responses.get(message.address, []):
            if isinstance(spec, (bytes, bytearray)):
                self.sock.sendto(spec, addr)
            else:
                reply_address, params = spec
                self.sock.sendto(_encode(reply_address, params), addr)

    def stop(self):
        self._stop.set()
        self.thread.join(timeout=1)
        self.sock.close()


@pytest.fixture
def server():
    srv = FakeServer()
    yield srv
    srv.stop()


def _client(server, timeout=1.0):
    return OSCClient(host="127.0.0.1", send_port=server.port, receive_port=0, timeout=timeout)


def test_send_is_fire_and_forget(server):
    with _client(server) as client:
        client.send("/live/song/set/tempo", 128.0)
        # Give the server a moment to receive.
        _wait_for(lambda: server.received)
    assert server.received[0] == ("/live/song/set/tempo", [128.0])


def test_request_returns_reply(server):
    server.responses["/live/song/get/tempo"] = [("/live/song/get/tempo", (120.0,))]
    with _client(server) as client:
        assert client.request("/live/song/get/tempo") == [120.0]


def test_request_validates_leading_args(server):
    server.responses["/live/clip_slot/get/has_clip"] = [
        ("/live/clip_slot/get/has_clip", (0, 1, True)),
    ]
    with _client(server) as client:
        assert client.request("/live/clip_slot/get/has_clip", 0, 1, match_leading=(0, 1)) == [
            0,
            1,
            True,
        ]


def test_request_skips_wrong_address_then_accepts(server):
    server.responses["/live/song/get/tempo"] = [
        ("/live/song/get/other", (1,)),
        ("/live/song/get/tempo", (120.0,)),
    ]
    with _client(server) as client:
        assert client.request("/live/song/get/tempo") == [120.0]


def test_request_skips_wrong_leading_then_accepts(server):
    server.responses["/live/track/get/has_midi_input"] = [
        ("/live/track/get/has_midi_input", (9, True)),  # wrong track index
        ("/live/track/get/has_midi_input", (0, True)),
    ]
    with _client(server) as client:
        result = client.request("/live/track/get/has_midi_input", 0, match_leading=(0,))
    assert result == [0, True]


def test_request_ignores_malformed_datagram(server):
    server.responses["/live/song/get/tempo"] = [
        b"this-is-not-an-osc-message",
        ("/live/song/get/tempo", (120.0,)),
    ]
    with _client(server) as client:
        assert client.request("/live/song/get/tempo") == [120.0]


def test_request_times_out_with_no_reply(server):
    with _client(server, timeout=0.3) as client:
        with pytest.raises(OSCTimeoutError):
            client.request("/live/song/get/tempo")


def test_send_bundle_delivers_messages_in_order(server):
    with _client(server) as client:
        client.send_bundle(
            [
                ("/live/clip/remove/notes", (0, 0, 60, 1, 0.0, 0.01)),
                ("/live/clip/add/notes", (0, 0, 62, 0.0, 1.0, 100, False)),
            ]
        )
        _wait_for(lambda: len(server.received) >= 2)
    addresses = [address for address, _ in server.received]
    assert addresses == ["/live/clip/remove/notes", "/live/clip/add/notes"]


def test_bound_port_is_reported(server):
    with _client(server) as client:
        assert client.receive_port > 0


def test_close_is_idempotent(server):
    client = _client(server)
    client.close()
    client.close()  # second close must not raise


def _wait_for(predicate, timeout=2.0):
    deadline = threading.Event()
    waited = 0.0
    step = 0.01
    while waited < timeout:
        if predicate():
            return
        deadline.wait(step)
        waited += step
    raise AssertionError("condition not met within timeout")
