"""xiaomi_s400_live — live weight + body composition from Xiaomi Body Composition Scale S400.

Public API:

    from xiaomi_s400_live import S400Scale, MiCloudClient, UserProfile, ScaleEvent

Auth/crypto modules are exposed for advanced use cases (custom transports,
testing) but most users only need the four names above.
"""

from .body import UserProfile, compute as compute_body_composition
from .cloud import DeviceCredentials, MiCloudClient, StaticCredentialsProvider
from .crypto import SessionKeys, decrypt_cmtp, derive_login_keys
from .scale import S400Scale, ScaleEvent

__all__ = [
    "S400Scale",
    "ScaleEvent",
    "MiCloudClient",
    "StaticCredentialsProvider",
    "DeviceCredentials",
    "UserProfile",
    "SessionKeys",
    "compute_body_composition",
    "decrypt_cmtp",
    "derive_login_keys",
]

__version__ = "0.1.0"
