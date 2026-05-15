"""Watch multiple scales concurrently.

Configure scales in MEMBERS — one entry per (mac, profile). Each scale runs
in its own task; a single MiCloudClient is shared (cached credentials).

    python examples/multi_scale.py
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from xiaomi_s400_live import MiCloudClient, S400Scale, UserProfile


load_dotenv()


# Edit MEMBERS for your household. MACs here, not in .env, since they're
# device identifiers (not secrets). Profiles can vary per user.
MEMBERS = [
    {
        "name": "alice",
        "mac": os.environ.get("SCALE_MAC", "CC:4D:75:XX:XX:XX"),
        "profile": UserProfile(sex="female", age_years=28, height_cm=162),
    },
    # Add more scales here; each gets its own connection + login session.
    # {
    #     "name": "bob",
    #     "mac": "CC:4D:75:YY:YY:YY",
    #     "profile": UserProfile(sex="male", age_years=35, height_cm=178),
    # },
]


async def watch(cloud: MiCloudClient, member: dict) -> None:
    while True:  # auto-reconnect loop
        try:
            async with S400Scale(
                mac=member["mac"],
                cloud=cloud,
                profile=member["profile"],
            ) as scale:
                async for event in scale.events():
                    if event.type == "final":
                        print(f"[{member['name']}] FINAL {event.weight_kg} kg "
                              f"imp={event.impedance_ohm}Ω "
                              f"body={event.body_composition}")
                    elif event.type == "live" and event.stable:
                        print(f"[{member['name']}] stable {event.weight_kg} kg")
        except Exception as exc:
            print(f"[{member['name']}] error: {exc!r}; reconnecting in 10s")
            await asyncio.sleep(10)


async def main():
    logging.basicConfig(level=logging.INFO)
    cloud = MiCloudClient(
        email=os.environ["MI_EMAIL"],
        password=os.environ["MI_PASSWORD"],
        cache_path="~/.s400_cache.json",
    )
    await asyncio.gather(*(watch(cloud, m) for m in MEMBERS))


if __name__ == "__main__":
    asyncio.run(main())
