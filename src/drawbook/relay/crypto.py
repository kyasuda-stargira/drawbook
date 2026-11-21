"""Sealing and signing for relay notices (PyNaCl / libsodium, available in every major language).

Wire format of the content the relay stores:
  SecretBox(content_key).encrypt(json({"manifest": {...}, "sig": b64(ed25519(canonical(manifest)))}))
and, per LP device, SealedBox(device_box_pk).encrypt(content_key).
"""
from __future__ import annotations

import hashlib
import json

import nacl.utils
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.secret import SecretBox
from nacl.signing import SigningKey, VerifyKey

from . import b64, unb64


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(pk_b64: str) -> str:
    """Short, readable key fingerprint to compare by phone (like checking bank details)."""
    h = hashlib.sha256(unb64(pk_b64)).hexdigest()[:20].upper()
    return " ".join(h[i:i + 4] for i in range(0, 20, 4))


def new_box_key() -> PrivateKey:
    return PrivateKey.generate()


def new_sign_key() -> SigningKey:
    return SigningKey.generate()


def seal(manifest: dict, signer: SigningKey, member_box_pks: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    """Return (ciphertext, {member_id: sealed content key})."""
    inner = canonical({"manifest": manifest, "sig": b64(signer.sign(canonical(manifest)).signature)})
    key = nacl.utils.random(SecretBox.KEY_SIZE)
    ct = bytes(SecretBox(key).encrypt(inner))
    keys = {mid: b64(SealedBox(PublicKey(unb64(pk))).encrypt(key)) for mid, pk in member_box_pks.items()}
    return ct, keys


class BadNotice(Exception):
    pass


def open_notice(ciphertext: bytes, sealed_key: str, box_sk: PrivateKey, gp_sign_pk: str) -> dict:
    """Decrypt and check the GP's signature; return the manifest. Raises BadNotice on any failure."""
    try:
        key = SealedBox(box_sk).decrypt(unb64(sealed_key))
        inner = json.loads(SecretBox(key).decrypt(ciphertext))
        manifest, sig = inner["manifest"], unb64(inner["sig"])
    except Exception as e:  # noqa: BLE001
        raise BadNotice(f"could not decrypt: {e}") from None
    try:
        VerifyKey(unb64(gp_sign_pk)).verify(canonical(manifest), sig)
    except Exception:  # noqa: BLE001
        raise BadNotice("GP signature does not match the GP's pinned key") from None
    return manifest
