# xiaomi-s400-live

Real-time weight + body composition from the **Xiaomi Body Composition Scale S400** (MJTZC01YM / `yunmai.scales.ms104`) over BLE, in Python.

Unlike passive advertisement scanning (which only emits a final reading 3–5s **after** the user stops moving), this library authenticates to the scale with the Mi Home v2 protocol and streams live weight via the proprietary GATT command channel.

## Features

- **Live weight stream** — every ~0.3s while standing on the scale, with a `stable` flag once the measurement settles
- **Final measurement** — full dump including weight, dual impedance, device timestamp, profile id
- **Body composition** — BMI, fat%, muscle, bone, water, visceral fat, metabolic age (formulas ported from `mnm-matin/miscale`)
- **Multi-scale** — one `MiCloudClient` shared across many `S400Scale` instances, each in its own asyncio task
- **Auto token rotation** — if Mi Home re-pairs and rotates the token, the library detects HMAC mismatch and refetches from Mi Cloud automatically

## Install

```bash
pip install xiaomi-s400-live              # core (bring your own bindkey + token)
pip install "xiaomi-s400-live[cloud]"     # + auto-fetch via micloud
```

## Running the examples

```bash
git clone https://github.com/YOURUSER/xiaomi-s400-live
cd xiaomi-s400-live
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # fill in SCALE_MAC + profile
```

Then pick one of two paths to get your scale's `bindkey` + 12-byte login `token`:

### Path A — static credentials (recommended)

Most accounts have 2FA enabled, which the `micloud` library cannot handle. Use
[Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
once (it does support 2FA + captcha interactively), save the output as
`credentials.json` (see `credentials.example.json`), then:

```bash
python examples/static_credentials.py
```

### Path B — automatic Mi Cloud login (no 2FA only)

If your Mi account has no 2FA, the library can fetch credentials each session:

```bash
# Add MI_EMAIL + MI_PASSWORD to .env first
python examples/single_scale.py
```

`MiCloudClient` caches to `~/.s400_cache.json` so it only hits the cloud once
per token rotation.

## Library usage

```python
import asyncio
from xiaomi_s400_live import S400Scale, MiCloudClient, UserProfile

async def main():
    cloud = MiCloudClient(
        email="you@example.com",
        password="...",
        cache_path="~/.s400_cache.json",
    )
    profile = UserProfile(sex="male", age_years=30, height_cm=175)

    async with S400Scale("AA:BB:CC:DD:EE:FF", cloud=cloud, profile=profile) as scale:
        async for event in scale.events():
            if event.type == "live":
                print(f"Live: {event.weight_kg} kg  stable={event.stable}")
            elif event.type == "final":
                print(f"Final: {event.weight_kg} kg")
                print(f"  Impedance: {event.impedance_ohm} Ω")
                print(f"  Body: {event.body_composition}")

asyncio.run(main())
```

On **macOS**, BLE addresses are opaque per-host UUIDs but the library scans by name-suffix (the last 4 hex digits of the MAC, e.g. `BD4F`), so just pass the real MAC.

## How it works

1. Connect via Bleak.
2. Subscribe to UPNP (`0x10`), AVDTP (`0x19`) and the encrypted channels CMTP (`0x1b`) / VEND1A (`0x1a`).
3. Run Mi Home v2 **LOGIN**:
   - exchange random keys with the device over AVDTP
   - derive `dev_key / app_key / dev_iv / app_iv` via HKDF-SHA256(`token`, salt = app_rand || dev_rand, info = `mible-login-info`)
   - verify with HMAC-SHA256 and confirm with `0x21 00 00 00` on UPNP
4. Pump multi-frame messages on CMTP, AES-CCM-decrypt with `dev_key + dev_iv + iter`, parse ASCII CSV payloads into `live` / `final` events.

Plain English: the scale will only emit measurements once you prove you're paired with the Mi Home account that owns it. The 12-byte BLE login token comes from Mi Cloud — `MiCloudClient` fetches it for you.

## Multi-scale

```python
from xiaomi_s400_live import S400Scale, MiCloudClient, UserProfile
import asyncio

async def watch(cloud, mac, profile):
    async with S400Scale(mac, cloud=cloud, profile=profile) as s:
        async for ev in s.events():
            if ev.type == "final":
                print(f"[{mac}] {ev.weight_kg} kg")

async def main():
    cloud = MiCloudClient(email=..., password=...)
    await asyncio.gather(
        watch(cloud, "CC:4D:75:AA:AA:AA", UserProfile("female", 28, 162)),
        watch(cloud, "CC:4D:75:BB:BB:BB", UserProfile("male",   34, 178)),
    )

asyncio.run(main())
```

The host's BLE adapter is the bottleneck — most stacks handle 5–7 concurrent GATT connections comfortably.

## Token rotation

The 12-byte BLE login token rotates whenever the scale is factory-reset or removed-and-re-added in Mi Home. The library handles this:

1. `S400Scale.__aenter__()` reads from cache, attempts login.
2. If `BadTokenError` (HMAC mismatch), the cache entry is invalidated and `MiCloudClient` refetches from Xiaomi Cloud.
3. Login is retried once with the new token.

If you don't want Mi Cloud access, pass `bindkey=` and `token=` directly and handle rotation yourself (re-extract via [PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)).

## Credits

The protocol and decoders were built on:

- [dnandha/miauth](https://github.com/dnandha/miauth) — Apache 2.0 — Mi Home v2 auth protocol reverse-engineering (Python + Java)
- [mnm-matin/miscale](https://github.com/mnm-matin/miscale) — MIT — S400 advertisement decoder + body composition formulas
- [PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) — getting bindkey + token from Mi Cloud
- [Bluetooth-Devices/xiaomi-ble](https://github.com/Bluetooth-Devices/xiaomi-ble) — passive MiBeacon parsing (used internally by Home Assistant)

The protocol is reverse-engineered; it can break on firmware updates. Tested against firmware `2.1.1_0006`.

## License

Apache 2.0
