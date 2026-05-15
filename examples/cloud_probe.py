"""Probe what fields micloud returns for your scale, so we know how to map them.

    export MI_EMAIL=...
    export MI_PASSWORD=...
    python examples/cloud_probe.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from micloud import MiCloud


load_dotenv()
TARGET_MAC = os.environ["SCALE_MAC"]


def main():
    mc = MiCloud(os.environ["MI_EMAIL"], os.environ["MI_PASSWORD"])
    if not mc.login():
        sys.exit("Mi Cloud login failed")

    for server in ["cn", "de", "us", "ru", "tw", "sg", "in", "i2"]:
        devices = mc.get_devices(country=server) or []
        if not devices:
            continue
        for d in devices:
            mac = (d.get("mac") or "").upper()
            if mac != TARGET_MAC.upper():
                continue
            print(f"=== server: {server} ===")
            print(json.dumps(d, indent=2, default=str))
            return

    sys.exit(f"No device with MAC {TARGET_MAC} found across servers.")


if __name__ == "__main__":
    main()
