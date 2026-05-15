"""Mi Home BLE login handshake for Xiaomi BLE scales.

Performs the LOGIN flow (assumes the scale is already registered to a Mi
Home account and you have the 12-byte token). Returns SessionKeys on success.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Callable

from bleak import BleakClient

from .crypto import SessionKeys, derive_login_keys, hmac_sha256
from .protocol import (
    AVDTP,
    CFM_LOGIN_OK,
    CMD_LOGIN,
    CMD_SEND_INFO,
    CMD_SEND_KEY,
    RCV_OK,
    RCV_RDY,
    UPNP,
)


logger = logging.getLogger(__name__)


class AuthError(RuntimeError):
    pass


class BadTokenError(AuthError):
    """HMAC verification failed — token is wrong or has rotated."""


class _NotifyHub:
    """Bridges BleakClient notify callbacks to per-UUID asyncio.Queues."""

    def __init__(self):
        self.queues: dict[str, asyncio.Queue[bytes]] = {}

    def queue(self, uuid: str) -> asyncio.Queue[bytes]:
        if uuid not in self.queues:
            self.queues[uuid] = asyncio.Queue()
        return self.queues[uuid]

    def make_callback(self, uuid: str) -> Callable[[int, bytearray], None]:
        q = self.queue(uuid)
        loop = asyncio.get_event_loop()

        def cb(_handle: int, data: bytearray) -> None:
            # Bleak callback runs on the loop thread; put_nowait is safe.
            try:
                q.put_nowait(bytes(data))
            except asyncio.QueueFull:
                logger.warning("notify queue full on %s; dropping", uuid)

        return cb


async def _wait(q: asyncio.Queue[bytes], timeout: float) -> bytes:
    return await asyncio.wait_for(q.get(), timeout=timeout)


async def _write(client: BleakClient, uuid: str, data: bytes) -> None:
    logger.debug("-> %s %s", uuid[:8], data.hex(" "))
    await client.write_gatt_char(uuid, data, response=False)


async def _write_parcel(client: BleakClient, uuid: str, data: bytes,
                        chunk_size: int = 18, frame_delay: float = 0.05) -> None:
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        n = i // chunk_size + 1
        framed = bytes([n & 0xFF, (n >> 8) & 0xFF]) + chunk
        await _write(client, uuid, framed)
        await asyncio.sleep(frame_delay)


async def _recv_multiframe(client: BleakClient, q: asyncio.Queue[bytes],
                           timeout: float = 5.0) -> bytes:
    first = await _wait(q, timeout)
    if len(first) < 6 or first[:3] != b"\x00\x00\x00":
        raise AuthError(f"unexpected first frame: {first.hex()}")
    expected = first[4] | (first[5] << 8)
    await _write(client, AVDTP, RCV_RDY)
    buf = b""
    for _ in range(expected):
        frame = await _wait(q, timeout)
        buf += frame[2:]
    await _write(client, AVDTP, RCV_OK)
    return buf


async def login(client: BleakClient, token: bytes,
                hub: _NotifyHub, timeout: float = 5.0) -> SessionKeys:
    """Execute Mi Home v2 LOGIN. Caller must have already started_notify
    on UPNP and AVDTP and routed callbacks into the hub."""
    if len(token) != 12:
        raise AuthError(f"token must be 12 bytes, got {len(token)}")

    avdtp_q = hub.queue(AVDTP)
    upnp_q  = hub.queue(UPNP)

    app_rand = secrets.token_bytes(16)
    logger.debug("app rand=%s", app_rand.hex())

    # Send CMD_LOGIN + our rand_key
    await _write(client, UPNP, CMD_LOGIN)
    await _write(client, AVDTP, CMD_SEND_KEY)
    rdy = await _wait(avdtp_q, timeout)
    if rdy != RCV_RDY:
        raise AuthError(f"expected RCV_RDY after CMD_SEND_KEY, got {rdy.hex()}")
    await _write_parcel(client, AVDTP, app_rand)
    ok = await _wait(avdtp_q, timeout)
    if ok != RCV_OK:
        raise AuthError(f"expected RCV_OK, got {ok.hex()}")

    # Receive device rand_key + remote info (HMAC)
    dev_rand = await _recv_multiframe(client, avdtp_q, timeout)
    if len(dev_rand) != 16:
        raise AuthError(f"bad dev rand len {len(dev_rand)}: {dev_rand.hex()}")
    logger.debug("dev rand=%s", dev_rand.hex())

    remote_info = await _recv_multiframe(client, avdtp_q, timeout)
    logger.debug("remote_info=%s", remote_info.hex())

    keys = derive_login_keys(token, app_rand, dev_rand)
    expected_remote = hmac_sha256(keys.dev_key, dev_rand + app_rand)
    if remote_info != expected_remote:
        raise BadTokenError("HMAC mismatch — token is wrong or has rotated")

    our_info = hmac_sha256(keys.app_key, app_rand + dev_rand)

    await _write(client, AVDTP, CMD_SEND_INFO)
    rdy = await _wait(avdtp_q, timeout)
    if rdy != RCV_RDY:
        raise AuthError(f"expected RCV_RDY for SEND_INFO, got {rdy.hex()}")
    await _write_parcel(client, AVDTP, our_info)
    ok = await _wait(avdtp_q, timeout)
    if ok != RCV_OK:
        raise AuthError(f"expected RCV_OK for SEND_INFO, got {ok.hex()}")

    result = await _wait(upnp_q, timeout)
    if result != CFM_LOGIN_OK:
        raise AuthError(f"login failed: {result.hex()}")

    return keys


def make_notify_hub() -> _NotifyHub:
    return _NotifyHub()
