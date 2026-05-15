"""Watch one scale: live weight + body composition.

Setup:
    cp .env.example .env   # then fill in values
    pip install -e ".[cloud,examples]"
    python examples/single_scale.py
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from xiaomi_s400_live import MiCloudClient, S400Scale, UserProfile


async def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cloud = MiCloudClient(
        email=os.environ["MI_EMAIL"],
        password=os.environ["MI_PASSWORD"],
        cache_path="~/.s400_cache.json",
    )

    profile = UserProfile(
        sex=os.environ.get("USER_SEX", "male"),
        age_years=int(os.environ.get("USER_AGE_YEARS", "30")),
        height_cm=int(os.environ.get("USER_HEIGHT_CM", "175")),
    )

    async with S400Scale(
        mac=os.environ["SCALE_MAC"],
        cloud=cloud,
        profile=profile,
    ) as scale:
        print("Step on the scale...")
        async for event in scale.events():
            if event.type == "live":
                bar = "█" * int((event.weight_kg or 0) / 2)
                stable = "★" if event.stable else " "
                print(f"\r{stable} {event.weight_kg:6.1f} kg  {bar}", end="", flush=True)
            elif event.type == "final":
                print()
                print(f"FINAL: {event.weight_kg} kg, impedance={event.impedance_ohm}Ω")
                if event.body_composition:
                    for k, v in event.body_composition.items():
                        print(f"  {k:22s} = {v}")
                print()


if __name__ == "__main__":
    asyncio.run(main())
