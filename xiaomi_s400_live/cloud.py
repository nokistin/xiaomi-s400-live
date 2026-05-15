"""Mi Cloud credentials helper with caching + auto-rotation.

Looks up bindkey + 12-byte BLE login token for a given MAC by logging into
Xiaomi Cloud as the account that owns the scale.

Uses `micloud` (https://github.com/squachen/micloud) under the hood.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceCredentials:
    mac: str            # uppercase AA:BB:CC:DD:EE:FF
    bindkey: bytes      # 16B for advertisement decryption
    token: bytes        # 12B for BLE GATT login
    did: str            # device id, e.g. blt.1.1lc4mu3k54c00
    server: str         # cn|de|us|ru|tw|sg|in|i2 — needed for future refreshes
    fetched_at: float   # unix timestamp


class StaticCredentialsProvider:
    """Read credentials from a JSON file produced by
    https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor

    Expected JSON shape (one or many devices):
        [
          {"mac": "AA:BB:...", "bindkey": "<hex32>", "token": "<hex24>",
           "did": "blt.1.1...", "server": "tw"},
          ...
        ]

    Drop-in replacement for `MiCloudClient` if Mi Cloud login is unreliable
    (2FA, captcha) — manual extract once, save JSON, never call cloud at runtime.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()
        raw = json.loads(self.path.read_text())
        if isinstance(raw, dict):
            raw = [raw]
        self._by_mac: dict[str, DeviceCredentials] = {}
        for entry in raw:
            mac = entry["mac"].upper()
            self._by_mac[mac] = DeviceCredentials(
                mac=mac,
                bindkey=bytes.fromhex(entry["bindkey"]),
                token=bytes.fromhex(entry["token"]),
                did=entry.get("did", ""),
                server=entry.get("server", ""),
                fetched_at=time.time(),
            )

    async def get(self, mac: str, *, force_refresh: bool = False) -> DeviceCredentials:
        mac = mac.upper()
        if mac not in self._by_mac:
            raise RuntimeError(
                f"MAC {mac} not found in {self.path}. "
                f"Available: {list(self._by_mac.keys())}"
            )
        if force_refresh:
            raise RuntimeError(
                f"Token rotated for {mac}. Re-run Xiaomi-cloud-tokens-extractor "
                f"and update {self.path}."
            )
        return self._by_mac[mac]

    def invalidate(self, mac: str) -> None:
        # Static provider can't refresh — leave entry, let next get() warn.
        logger.warning(
            "static credentials can't auto-refresh; re-extract token for %s manually",
            mac.upper(),
        )


class MiCloudClient:
    """Fetches and caches Xiaomi Cloud credentials for BLE scales.

    Single MiCloudClient can serve multiple devices; cache stores per-MAC.
    """

    def __init__(
        self,
        email: str,
        password: str,
        cache_path: Path | str | None = None,
        servers: list[str] | None = None,
    ):
        self.email = email
        self.password = password
        self.cache_path = Path(cache_path).expanduser() if cache_path else None
        self.servers = servers or ["cn", "de", "us", "ru", "tw", "sg", "in", "i2"]
        self._cache: dict[str, DeviceCredentials] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            raw = json.loads(self.cache_path.read_text())
        except Exception as exc:
            logger.warning("Cache read failed (%s); starting fresh", exc)
            return
        for mac, entry in raw.items():
            self._cache[mac.upper()] = DeviceCredentials(
                mac=entry["mac"],
                bindkey=bytes.fromhex(entry["bindkey"]),
                token=bytes.fromhex(entry["token"]),
                did=entry["did"],
                server=entry["server"],
                fetched_at=entry["fetched_at"],
            )

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            mac: {
                "mac": c.mac,
                "bindkey": c.bindkey.hex(),
                "token": c.token.hex(),
                "did": c.did,
                "server": c.server,
                "fetched_at": c.fetched_at,
            }
            for mac, c in self._cache.items()
        }
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(serializable, indent=2))
        tmp.replace(self.cache_path)

    async def get(self, mac: str, *, force_refresh: bool = False) -> DeviceCredentials:
        """Return credentials for a scale by MAC. Uses cache unless force_refresh."""
        mac = mac.upper()
        if not force_refresh and mac in self._cache:
            return self._cache[mac]
        creds = await self._fetch_from_cloud(mac)
        self._cache[mac] = creds
        self._save_cache()
        return creds

    def invalidate(self, mac: str) -> None:
        """Drop cached credentials for a MAC, forcing the next get() to refetch."""
        self._cache.pop(mac.upper(), None)
        self._save_cache()

    async def _fetch_from_cloud(self, mac: str) -> DeviceCredentials:
        """Login to Mi Cloud, scan known servers, return matching device."""
        # Lazy import — micloud is optional unless cloud fetch is needed.
        try:
            from micloud import MiCloud  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Install the `micloud` package (pip install micloud) "
                "to enable automatic credential fetch."
            ) from exc

        def _blocking_lookup() -> DeviceCredentials:
            mc = MiCloud(self.email, self.password)
            if not mc.login():
                raise RuntimeError("Mi Cloud login failed (check email/password).")
            for server in self.servers:
                devices = mc.get_devices(country=server) or []
                for d in devices:
                    if (d.get("mac") or "").upper() != mac:
                        continue
                    bindkey_hex = d.get("BLE KEY") or d.get("ble_key") or d.get("blt_key")
                    token_hex   = d.get("token")
                    did         = d.get("did", "")
                    if not bindkey_hex or not token_hex:
                        raise RuntimeError(
                            f"Device {mac} on server '{server}' missing bindkey/token. "
                            "Maybe not a v5 BLE device."
                        )
                    return DeviceCredentials(
                        mac=mac,
                        bindkey=bytes.fromhex(bindkey_hex),
                        token=bytes.fromhex(token_hex),
                        did=did,
                        server=server,
                        fetched_at=time.time(),
                    )
            raise RuntimeError(
                f"No device with MAC {mac} found in Mi Cloud across servers {self.servers}. "
                "Make sure the scale is paired in Mi Home with this account."
            )

        return await asyncio.to_thread(_blocking_lookup)
