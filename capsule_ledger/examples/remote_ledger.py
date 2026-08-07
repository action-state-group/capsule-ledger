# SPDX-License-Identifier: Apache-2.0
"""HTTP ``LedgerAPI`` binding for a hosted ledger-cloud tenant.

``capsule_ledger.ledger.api.LedgerAPI`` is deliberately transport-agnostic
(see that module's own docstring) so a remote binding is "no API change, no
caller-visible difference" from the local ``LedgerStore`` -- nothing in
capsule-ledger built that binding yet. This is a small one: it talks to the
same ``/v1/capsules`` transport binding a hosted ledger-cloud tenant service
exposes -- ``POST`` to append, ``GET`` to scan/fetch, ``GET .../verify`` to
verify -- one request/response shape per ``LedgerAPI`` method, no invented
wire shapes. The tenant is resolved server-side from the ``X-API-Key``
header; there is no separate tenant-id parameter here.

``find_gaps`` has no server endpoint yet, so it raises rather than guessing
at one -- the same "fail loud, not silently" rule
``capsule_ledger.mcp.config.open_backend`` already applies to its own local/
remote backend seam.

Uses only the standard library (``urllib``) -- this stays a zero-extra-
dependency seam; the only new dependency this example set introduces is
``capsule-emit`` itself (see ``pyproject.toml``'s ``examples`` extra).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import asdict

from agent_action_capsule import VerificationResult
from agent_action_capsule.verify import Finding

from capsule_ledger.ledger.api import LedgerAPI, ScanQuery
from capsule_ledger.ledger.records import ChainGap, LedgerRecord

__all__ = ["RemoteLedgerAPI"]


class RemoteLedgerAPI(LedgerAPI):
    """``LedgerAPI`` bound over HTTP to a hosted ledger-cloud tenant.

    Config-pointable per ``two_agents.py``'s own backend seam: swapping this
    in for a local ``LedgerStore`` is an env var / CLI flag away (see that
    module's ``_open_backend``), not a code change -- every caller only ever
    sees the ``LedgerAPI`` Protocol.
    """

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _request(
        self, method: str, path: str, *, params: dict | None = None, body: dict | None = None
    ) -> object:
        url = f"{self._base_url}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", self._api_key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 -- fixed https(s) tenant base_url, operator-supplied
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
        return json.loads(raw) if raw else None

    @staticmethod
    def _to_record(data: dict) -> LedgerRecord:
        return LedgerRecord(
            seq=data["seq"],
            capsule_id=data["capsule_id"],
            capsule=data["capsule"],
            segment=data["segment"],
            consequential=data["consequential"],
        )

    def append(self, capsule: dict, *, consequential: bool = True) -> LedgerRecord:
        data = self._request("POST", "/v1/capsules", body={"capsule": capsule, "consequential": consequential})
        return self._to_record(data)

    def scan(self, query: ScanQuery | None = None) -> Iterator[LedgerRecord]:
        data = self._request("GET", "/v1/capsules", params=asdict(query or ScanQuery()))
        for item in data or []:
            yield self._to_record(item)

    def fetch(self, capsule_id: str) -> LedgerRecord | None:
        data = self._request("GET", f"/v1/capsules/{capsule_id}")
        return self._to_record(data) if data is not None else None

    def verify(self, capsule_id: str) -> VerificationResult | None:
        data = self._request("GET", f"/v1/capsules/{capsule_id}/verify")
        if data is None:
            return None
        findings = [Finding(**f) for f in data.get("findings", [])]
        return VerificationResult(
            ok=data["ok"],
            findings=findings,
            assurance=data.get("assurance", {}),
            capsule_id=data.get("capsule_id"),
        )

    def find_gaps(self) -> list[ChainGap]:
        raise NotImplementedError(
            "RemoteLedgerAPI.find_gaps: the hosted ledger-cloud tenant's HTTP transport "
            "has no /v1/capsules/gaps-style endpoint yet -- not wired up server-side."
        )
