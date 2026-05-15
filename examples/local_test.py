"""Quick local test — uses bindkey + token from .env, no Mi Cloud login needed.

Use this when you've already extracted credentials via
https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor and don't
want the library to call Mi Cloud each session.

Setup:
    cp .env.example .env
    # add to .env:
    #   BINDKEY_HEX=<32 hex chars>
    #   TOKEN_HEX=<24 hex chars>
    pip install -e ".[examples]"
    python examples/local_test.py
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from xiaomi_s400_live import S400Scale, UserProfile


async def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    profile = UserProfile(
        sex=os.environ.get("USER_SEX", "male"),
        age_years=int(os.environ.get("USER_AGE_YEARS", "30")),
        height_cm=int(os.environ.get("USER_HEIGHT_CM", "175")),
    )

    async with S400Scale(
        mac=os.environ["SCALE_MAC"],
        bindkey=bytes.fromhex(os.environ["BINDKEY_HEX"]),
        token=bytes.fromhex(os.environ["TOKEN_HEX"]),
        profile=profile,
    ) as scale:
        print("Step on the scale (Ctrl+C to stop)...")
        async for event in scale.events():
            if event.type == "live":
                star = "*" if event.stable else " "
                print(f"\r{star} {event.weight_kg:6.1f} kg", end="", flush=True)
            elif event.type == "final":
                print()
                print(f"FINAL: {event.weight_kg} kg, "
                      f"impedance={event.impedance_ohm}Ω, "
                      f"profile_id={event.profile_id}, "
                      f"timestamp={event.timestamp}")
                if event.body_composition:
                    for k, v in event.body_composition.items():
                        print(f"  {k:22s} = {v}")
                print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
