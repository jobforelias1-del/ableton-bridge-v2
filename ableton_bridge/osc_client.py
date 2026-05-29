"""Low-level synchronous OSC transport for talking to AbletonOSC.

Implements request/reply over UDP against AbletonOSC's protocol:

* Messages are sent to ``send_port`` (default 11000).
* AbletonOSC sends replies to ``receive_port`` (default 11001), reusing the
  *same* OSC address as the request.
* Only *read* handlers reply. ``set``/method/``add``/``remove`` handlers are
  fire-and-forget and produce no reply -- and, crucially, no error reply -- so a
  failed write is silent at the protocol level.

The client uses a single UDP socket bound to ``receive_port`` for both sending
and receiving (AbletonOSC always replies to the fixed response port, so this is
the natural arrangement). A lock serialises access so one request/reply exchange
completes before the next begins; concurrent in-flight requests to the same
address could not be disambiguated anyway, since the reply reuses the request
address.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Iterable, Sequence

from pythonosc.osc_bundle_builder import IMMEDIATELY, OscBundleBuilder
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from .exceptions import OSCTimeoutError

logger = logging.getLogger("ableton_bridge.osc")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SEND_PORT = 11000
DEFAULT_RECEIVE_PORT = 11001
DEFAULT_TIMEOUT = 5.0

_RECV_BUFSIZE = 65536


def _build_message(address: str, args: Iterable) -> bytes:
    """Encode an OSC message to a datagram.

    Args:
        address: The OSC address pattern.
        args: The message arguments.

    Returns:
        The encoded datagram bytes.
    """
    builder = OscMessageBuilder(address)
    for arg in args:
        builder.add_arg(arg)
    return builder.build().dgram


class OSCClient:
    """Synchronous OSC client for AbletonOSC.

    The client may be used as a context manager, which closes the socket on
    exit::

        with OSCClient() as osc:
            osc.send("/live/song/start_playing")
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Bind the transport socket and prepare to talk to AbletonOSC.

        Args:
            host: Hostname/IP where AbletonOSC is listening. Defaults to
                ``127.0.0.1``.
            send_port: UDP port AbletonOSC listens on. Defaults to 11000.
            receive_port: UDP port AbletonOSC sends replies to, and the port this
                client binds. Defaults to 11001. Pass ``0`` to bind an ephemeral
                port (useful in tests).
            timeout: Default seconds to wait for a reply before raising
                :class:`~ableton_bridge.exceptions.OSCTimeoutError`.
        """
        self.host = host
        self.send_port = send_port
        self.timeout = timeout
        self._lock = threading.Lock()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("", receive_port))
        self.receive_port = self._socket.getsockname()[1]
        logger.info(
            "OSC transport bound to receive port %d, sending to %s:%d",
            self.receive_port,
            host,
            send_port,
        )

    def send(self, address: str, *args) -> None:
        """Send a fire-and-forget OSC message (no reply is expected).

        Args:
            address: The OSC address (e.g. ``/live/song/set/tempo``).
            *args: The message arguments.
        """
        dgram = _build_message(address, args)
        logger.debug("OSC send %s %s", address, list(args))
        with self._lock:
            self._socket.sendto(dgram, (self.host, self.send_port))

    def send_bundle(self, messages: Sequence[tuple[str, Sequence]]) -> None:
        """Send several messages together in a single OSC bundle (one datagram).

        AbletonOSC processes the messages in order within the bundle, so this is
        used to batch a sequence such as remove-then-add into a single
        round-trip with a defined ordering.

        Args:
            messages: A sequence of ``(address, args)`` pairs.
        """
        builder = OscBundleBuilder(IMMEDIATELY)
        for address, args in messages:
            message_builder = OscMessageBuilder(address)
            for arg in args:
                message_builder.add_arg(arg)
            builder.add_content(message_builder.build())
        dgram = builder.build().dgram
        logger.debug("OSC send bundle of %d messages: %s", len(messages), [m[0] for m in messages])
        with self._lock:
            self._socket.sendto(dgram, (self.host, self.send_port))

    def request(self, address: str, *args, match_leading: Sequence = ()) -> list:
        """Send a message and wait for the reply on the same OSC address.

        Args:
            address: OSC address to send, and to match the reply against.
            *args: Arguments to send.
            match_leading: Optional leading reply arguments that must match
                (typically the echoed track/clip/device indices), used to guard
                against stale replies from earlier requests or listeners.

        Returns:
            The reply parameters as a list (including any echoed leading args).

        Raises:
            OSCTimeoutError: If no matching reply arrives within ``timeout``.
        """
        dgram = _build_message(address, args)
        match_leading = tuple(match_leading)
        with self._lock:
            self._drain()
            logger.debug("OSC request %s %s", address, list(args))
            self._socket.sendto(dgram, (self.host, self.send_port))
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._socket.settimeout(remaining)
                try:
                    data, _ = self._socket.recvfrom(_RECV_BUFSIZE)
                except TimeoutError:
                    break
                try:
                    reply = OscMessage(data)
                except Exception:  # noqa: BLE001 - tolerate any malformed datagram
                    logger.debug("Ignoring undecodable datagram (%d bytes)", len(data))
                    continue
                if reply.address != address:
                    logger.debug(
                        "Ignoring reply on %s while waiting for %s", reply.address, address
                    )
                    continue
                params = list(reply.params)
                if match_leading and tuple(params[: len(match_leading)]) != match_leading:
                    logger.debug(
                        "Ignoring %s reply with leading %s != %s",
                        address,
                        params[: len(match_leading)],
                        match_leading,
                    )
                    continue
                logger.debug("OSC reply %s %s", address, params)
                return params
        raise OSCTimeoutError(
            f"No reply to {address} within {self.timeout}s "
            f"(is Ableton Live running with AbletonOSC enabled on {self.host}:{self.send_port}?)"
        )

    def _drain(self) -> None:
        """Discard any datagrams already queued on the socket.

        Draining before a request ensures a late reply to a previous request (or
        an unsolicited listener update) cannot be mistaken for this request's
        reply.
        """
        self._socket.settimeout(0)
        try:
            while True:
                try:
                    self._socket.recvfrom(_RECV_BUFSIZE)
                except (TimeoutError, BlockingIOError):
                    return
                except OSError:
                    return
        finally:
            self._socket.settimeout(self.timeout)

    def close(self) -> None:
        """Close the underlying socket."""
        self._socket.close()

    def __enter__(self) -> OSCClient:
        """Enter the context manager.

        Returns:
            This client.
        """
        return self

    def __exit__(self, *exc) -> None:
        """Close the socket on context-manager exit."""
        self.close()
