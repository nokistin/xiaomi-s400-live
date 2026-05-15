"""Mi Home BLE auth crypto: HKDF + HMAC + AES-CCM helpers."""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


@dataclass(frozen=True)
class SessionKeys:
    dev_key: bytes  # 16B - device → app encryption key
    app_key: bytes  # 16B - app → device encryption key
    dev_iv:  bytes  # 4B
    app_iv:  bytes  # 4B


def derive_login_keys(token: bytes, app_rand: bytes, dev_rand: bytes) -> SessionKeys:
    """HKDF-SHA256 to derive 4 session values from token + 32B salt."""
    salt = app_rand + dev_rand
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=64,
        salt=salt,
        info=b"mible-login-info",
        backend=default_backend(),
    ).derive(token)
    return SessionKeys(
        dev_key=derived[0:16],
        app_key=derived[16:32],
        dev_iv=derived[32:36],
        app_iv=derived[36:40],
    )


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    h = HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def decrypt_cmtp(keys: SessionKeys, raw: bytes) -> bytes | None:
    """Decrypt a CMTP message from the device.

    Format: [iter_LE_2B][ciphertext_with_4B_tag]
    Nonce: dev_iv(4) || zeros(4) || iter(2) || zeros(2)  = 12B
    """
    if len(raw) < 6:  # iter(2) + at least tag(4)
        return None
    try:
        it = raw[:2]
        ct = raw[2:]
        nonce = keys.dev_iv + bytes(4) + it + bytes(2)
        return AESCCM(keys.dev_key, tag_length=4).decrypt(nonce, ct, None)
    except Exception:
        return None


def encrypt_for_device(keys: SessionKeys, iter_counter: int, plaintext: bytes) -> bytes:
    """Encrypt a plaintext command for sending to device.

    Returns [iter_LE_2B][ciphertext_with_4B_tag]. Caller wraps in framing.
    """
    it_bytes = iter_counter.to_bytes(2, "little")
    nonce = keys.app_iv + bytes(4) + it_bytes + bytes(2)
    ct = AESCCM(keys.app_key, tag_length=4).encrypt(nonce, plaintext, None)
    return it_bytes + ct
