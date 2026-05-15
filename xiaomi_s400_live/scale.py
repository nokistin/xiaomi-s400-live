"""High-level S400 client: connect → login → stream live + final events.

Usage:
    from xiaomi_s400_live import S400Scale, UserProfile, MiCloudClient

    cloud = MiCloudClient(email="...", password="...",
                          cache_path="~/.s400_cache.json")
    profile = UserProfile(sex="male", age_years=30, height_cm=175)

    async with S400Scale("AA:BB:CC:DD:EE:FF", cloud=cloud,
                         profile=profile) as scale:
        async for event in scale.events():
            print(event)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from bleak import BleakClient, BleakScanner

from . import body as body_mod
from .auth import AuthError, BadTokenError, login, make_notify_hub
from .cloud import DeviceCredentials, MiCloudClient, StaticCredentialsProvider
from .crypto import SessionKeys, decrypt_cmtp
from .protocol import (
    AVDTP,
    AVCTP,
    CMTP,
    RCV_OK,
    RCV_RDY,
    UPNP,
    VEND1A,
    VEND1C,
)


logger = logging.getLogger(__name__)


@dataclass
class ScaleEvent:
    """Either a 'live' frame (weight updating) or 'final' (full body comp dump)."""
    type: str            # "live" | "final" | "raw"
    weight_kg: float | None = None
    stable: bool = False
    impedance_ohm: float | None = None        # final-only
    impedance_low_ohm: float | None = None    # final-only
    profile_id: int | None = None             # final-only (which user on scale)
    timestamp: int | None = None              # final-only (device unix time)
    body_composition: dict | None = None      # final-only, if user profile given
    raw_plaintext: bytes | None = None        # for debugging / 'raw' type


def _parse_payload(pt: bytes) -> dict | None:
    """Parse a decrypted CMTP plaintext into structured fields.

    Format (observed on yunmai.scales.ms104 / S400):
        LL 20 CC 00 07 08 PP 00 01 PP 00 SS a0 <ascii_csv>
    Live (2 fields): "weight_x10,stable_flag"
    Final (32 fields): "0,0,profile,weight_x10,stable,2,unix_ts,0..0,imp_x10,imp_low_x10"
    """
    idx = pt.find(b"\xa0")
    if idx < 0:
        return None
    s = pt[idx + 1:].decode("ascii", errors="replace").rstrip("\x00").strip()
    parts = s.split(",")

    def _i(p: str) -> int | None:
        return int(p) if p.lstrip("-").isdigit() else None

    if len(parts) == 2:
        w = _i(parts[0])
        return {
            "type": "live",
            "weight_kg": w / 10 if w is not None else None,
            "stable": parts[1] == "1",
        }
    if len(parts) >= 8:
        w = _i(parts[3])
        imp = _i(parts[-2])
        imp_low = _i(parts[-1])
        return {
            "type": "final",
            "profile_id": _i(parts[2]),
            "weight_kg": w / 10 if w is not None else None,
            "stable": parts[4] == "1",
            "timestamp": _i(parts[6]),
            "impedance_ohm": imp / 10 if imp is not None else None,
            "impedance_low_ohm": imp_low / 10 if imp_low is not None else None,
        }
    return None


class S400Scale:
    """Single-scale client.

    For multiple scales, create one S400Scale per device and run them
    concurrently with asyncio.gather().
    """

    def __init__(
        self,
        mac: str,
        *,
        cloud: MiCloudClient | StaticCredentialsProvider | None = None,
        bindkey: bytes | None = None,
        token: bytes | None = None,
        profile: body_mod.UserProfile | None = None,
        connect_timeout: float = 30.0,
    ):
        self.mac = mac.upper()
        self.cloud = cloud
        self._bindkey = bindkey
        self._token = token
        self.profile = profile
        self.connect_timeout = connect_timeout

        if not (self.cloud or (self._bindkey and self._token)):
            raise ValueError(
                "Provide either a MiCloudClient (auto-fetch) "
                "or explicit bindkey + token.")

        self._client: BleakClient | None = None
        self._keys: SessionKeys | None = None
        self._hub = make_notify_hub()
        self._event_queue: asyncio.Queue[ScaleEvent] = asyncio.Queue()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def _credentials(self, *, force_refresh: bool = False) -> tuple[bytes, bytes]:
        if force_refresh or not (self._bindkey and self._token):
            if not self.cloud:
                raise RuntimeError("No cloud client to refresh credentials.")
            creds = await self.cloud.get(self.mac, force_refresh=force_refresh)
            self._bindkey = creds.bindkey
            self._token = creds.token
        assert self._bindkey is not None and self._token is not None
        return self._bindkey, self._token

    async def _connect(self) -> BleakClient:
        # On macOS the BLE address is an opaque UUID, not the real MAC.
        # Scan to find the device by either MAC (Linux) or by name+MAC suffix (macOS).
        last4 = self.mac.replace(":", "")[-4:].lower()

        def matcher(device, adv) -> bool:
            if device.address.upper() == self.mac:
                return True
            name = (adv.local_name or device.name or "").lower()
            return last4 in name

        logger.info("scanning for scale %s ...", self.mac)
        dev = await BleakScanner.find_device_by_filter(matcher, timeout=20.0)
        if not dev:
            raise RuntimeError(f"scale {self.mac} not found in BLE range")

        client = BleakClient(dev, timeout=self.connect_timeout)
        await client.connect()
        return client

    async def _start_notify_all(self) -> None:
        assert self._client is not None
        for uuid in (UPNP, AVDTP, AVCTP, VEND1A, CMTP, VEND1C):
            try:
                await self._client.start_notify(uuid, self._hub.make_callback(uuid))
            except Exception as exc:
                logger.debug("subscribe %s failed (skipping): %s", uuid[:8], exc)

    async def _login_with_rotation(self) -> SessionKeys:
        """Try login. On HMAC failure, refresh token from cloud and retry once."""
        assert self._client is not None
        _, token = await self._credentials()
        try:
            return await login(self._client, token, self._hub)
        except BadTokenError:
            if not self.cloud:
                raise
            logger.warning("token rejected; refreshing from Mi Cloud")
            self.cloud.invalidate(self.mac)
            _, token = await self._credentials(force_refresh=True)
            return await login(self._client, token, self._hub)

    async def _cmtp_pump(self) -> None:
        """Drain CMTP notifications, reassemble multi-frame messages, decrypt, emit."""
        assert self._client is not None and self._keys is not None
        q = self._hub.queue(CMTP)
        expected = 0
        buf = b""
        while not self._stop.is_set():
            try:
                data = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Header: 00 00 00 SS LL 00
            if len(data) >= 6 and data[:3] == b"\x00\x00\x00" and data[5] == 0:
                expected = data[4]
                buf = b""
                await self._client.write_gatt_char(CMTP, RCV_RDY, response=False)
                continue

            # Data frame: NN 00 <payload>
            if len(data) >= 2 and data[1] == 0 and expected > 0:
                frame_num = data[0]
                buf += data[2:]
                if frame_num >= expected:
                    await self._handle_full(buf)
                    await self._client.write_gatt_char(CMTP, RCV_OK, response=False)
                    expected = 0
                    buf = b""

    async def _handle_full(self, ciphertext: bytes) -> None:
        assert self._keys is not None
        pt = decrypt_cmtp(self._keys, ciphertext)
        if pt is None:
            logger.warning("decrypt failed on %s", ciphertext.hex())
            return
        parsed = _parse_payload(pt)
        if parsed is None:
            await self._event_queue.put(ScaleEvent(type="raw", raw_plaintext=pt))
            return

        ev_type = parsed.pop("type")
        event = ScaleEvent(type=ev_type, **parsed, raw_plaintext=pt)

        # Body composition for final frames
        if (ev_type == "final"
                and self.profile is not None
                and event.weight_kg is not None
                and (event.impedance_ohm or event.impedance_low_ohm)):
            imp = event.impedance_ohm or event.impedance_low_ohm or 0
            try:
                event.body_composition = body_mod.compute(
                    event.weight_kg, imp, self.profile)
            except Exception as exc:
                logger.warning("body composition failed: %s", exc)

        await self._event_queue.put(event)

    async def __aenter__(self) -> "S400Scale":
        self._client = await self._connect()
        await self._start_notify_all()
        await asyncio.sleep(0.3)  # let device settle
        self._keys = await self._login_with_rotation()
        logger.info("logged into %s", self.mac)
        self._tasks.append(asyncio.create_task(self._cmtp_pump()))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception as exc:
                logger.debug("disconnect error: %s", exc)

    async def events(self) -> AsyncIterator[ScaleEvent]:
        """Async iterator over scale events until stopped."""
        while not self._stop.is_set():
            try:
                ev = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            yield ev

    def stop(self) -> None:
        self._stop.set()
