"""Use credentials JSON file from Xiaomi-cloud-tokens-extractor.

Avoids runtime Mi Cloud login (which fails with 2FA/captcha on `micloud`).
Extract credentials once with:
    https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor

Save the output as `credentials.json` (see format below), then:
    python examples/static_credentials.py

Expected JSON shape (one device or a list):
[
  {
    "mac": "AA:BB:CC:DD:EE:FF",
    "bindkey": "<32 hex chars>",
    "token":   "<24 hex chars>",
    "did":     "blt.1.1...",
    "server":  "tw"
  }
]
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from xiaomi_s400_live import S400Scale, StaticCredentialsProvider, UserProfile


async def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    creds = StaticCredentialsProvider(
        os.environ.get("CREDENTIALS_JSON", "credentials.json")
    )

    profile = UserProfile(
        sex=os.environ.get("USER_SEX", "male"),
        age_years=int(os.environ.get("USER_AGE_YEARS", "30")),
        height_cm=int(os.environ.get("USER_HEIGHT_CM", "175")),
    )

    async with S400Scale(
        mac=os.environ["SCALE_MAC"],
        cloud=creds,
        profile=profile,
    ) as scale:
        print("Step on the scale...")
        async for event in scale.events():
            if event.type == "live":
                star = "★" if event.stable else " "
                print(f"\r{star} {event.weight_kg:6.1f} kg", end="", flush=True)
            elif event.type == "final":
                print()
                print(f"FINAL: {event.weight_kg} kg, impedance={event.impedance_ohm}Ω")
                if event.body_composition:
                    for k, v in event.body_composition.items():
                        print(f"  {k:22s} = {v}")
                print()


if __name__ == "__main__":
    asyncio.run(main())
