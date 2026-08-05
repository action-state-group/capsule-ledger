# SPDX-License-Identifier: Apache-2.0
"""Signing-key abstraction for decision capsules.

Gating decisions doc §1: "Signing key unavailable -> Fail closed. An
unsigned record is not a record." v0 has no COSE/asymmetric signer --
capsules stay ``attestation_mode: self_attested`` throughout this package,
matching every other capsule the reference library builds. This is a local
HMAC-SHA256 "signature": enough to make key material a real, checkable
precondition and to make the signature field itself tamper-evident (it is
committed into ``capsule_id``, see ``capsule.py``), without pulling in a
cryptography dependency this package doesn't otherwise need.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["Signer", "LocalSigner", "SigningKeyUnavailable"]


class SigningKeyUnavailable(Exception):
    """No signing key is available right now.

    Raised by whatever supplies a ``Signer`` to the engine (e.g. a key
    provider callable) -- never by ``Signer.sign()`` itself. A caller that
    cannot produce a ``Signer`` must not attempt to build a capsule at all;
    that fail-closed gate lives in ``engine.py``.
    """


@runtime_checkable
class Signer(Protocol):
    key_id: str
    algorithm: str

    def sign(self, digest: str) -> str: ...


@dataclass(frozen=True)
class LocalSigner:
    """An in-process HMAC-SHA256 signer over a node-local secret."""

    key_id: str
    secret: bytes
    algorithm: str = "hmac-sha256"

    def sign(self, digest: str) -> str:
        return hmac.new(self.secret, digest.encode("ascii"), hashlib.sha256).hexdigest()
