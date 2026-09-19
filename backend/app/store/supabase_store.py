"""Supabase (PostgREST) backend.

Used whenever SUPABASE_URL and SUPABASE_SECRET_KEY are both set. Talks to
PostgREST directly rather than through supabase-py so that every non-2xx
response becomes a loud PersistenceError instead of a quietly empty result.

Table DDL lives in sql/001_generations.sql and must be applied once via the
Supabase SQL editor — PostgREST cannot issue DDL.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..models import Correction, Generation, GenerationCreate
from .errors import NotFoundError, PersistenceError

TABLE = "generations"
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class SupabaseStore:
    backend_name = "supabase"

    def __init__(self, url: str, secret_key: str):
        if not url or not secret_key:
            raise PersistenceError(
                "init",
                "SUPABASE_URL and SUPABASE_SECRET_KEY must both be set for the supabase backend",
            )
        self.base = url.rstrip("/")
        self.endpoint = f"{self.base}/rest/v1/{TABLE}"
        self._headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }

    def _request(self, operation: str, method: str, **kw: Any) -> list[dict]:
        url = kw.pop("url", self.endpoint)
        headers = {**self._headers, **kw.pop("headers", {})}
        try:
            with httpx.Client(timeout=_TIMEOUT) as c:
                r = c.request(method, url, headers=headers, **kw)
        except httpx.HTTPError as e:
            # Network-level failure. Loud, never swallowed.
            raise PersistenceError(operation, f"transport error: {e}") from e
        if r.status_code >= 400:
            raise PersistenceError(operation, r.text[:500], status=r.status_code)
        if not r.content:
            return []
        data = r.json()
        return data if isinstance(data, list) else [data]

    @staticmethod
    def _to_model(row: dict) -> Generation:
        row = dict(row)
        row["id"] = str(row["id"])
        if row.get("propagated_from") is not None:
            row["propagated_from"] = str(row["propagated_from"])
        row["placement"] = row.get("placement") or {}
        return Generation(**row)

    def health(self) -> dict:
        rows = self._request(
            "health", "GET", params={"select": "id", "limit": 1},
            headers={"Prefer": "count=exact"},
        )
        return {"backend": self.backend_name, "ok": True, "url": self.base, "sample": len(rows)}

    def save_generation(self, payload: GenerationCreate) -> Generation:
        body = {
            "address": payload.address,
            "lat": payload.lat,
            "lng": payload.lng,
            "source_photo": payload.source_photo,
            "artifact": payload.artifact,
            "placement": payload.placement.model_dump(),
            "mesh_url": payload.mesh_url,
            "world_state": payload.world_state,
            "confidence_state": payload.resolved_confidence_state(),
            "propagated_from": payload.propagated_from,
        }
        # Plain POST, never an upsert: one row per generation (step 11).
        rows = self._request(
            "save_generation", "POST", json=body,
            headers={"Prefer": "return=representation"},
        )
        if not rows:
            raise PersistenceError(
                "save_generation", "insert returned no row — write may not have persisted"
            )
        return self._to_model(rows[0])

    def get_generation(self, generation_id: str) -> Generation:
        rows = self._request(
            "get_generation", "GET",
            params={"id": f"eq.{generation_id}", "select": "*", "limit": 1},
        )
        if not rows:
            raise NotFoundError("get_generation", f"no generation with id {generation_id!r}")
        return self._to_model(rows[0])

    def list_generations(self) -> list[Generation]:
        rows = self._request(
            "list_generations", "GET",
            params={"select": "*", "order": "created_at.asc"},
        )
        return [self._to_model(r) for r in rows]

    def get_history_for_address(self, address: str) -> list[Generation]:
        rows = self._request(
            "get_history_for_address", "GET",
            params={"address": f"eq.{address}", "select": "*", "order": "created_at.asc"},
        )
        return [self._to_model(r) for r in rows]

    def apply_correction(self, generation_id: str, correction: Correction) -> Generation:
        current = self.get_generation(generation_id)
        placement = dict(current.placement)
        if correction.rotationDegrees is not None:
            placement["rotationDegrees"] = correction.rotationDegrees
        if correction.scale is not None:
            placement["scale"] = correction.scale
        if correction.position is not None:
            placement["position"] = correction.position
        placement["confidence"] = "manually-verified"
        rows = self._request(
            "apply_correction", "PATCH",
            params={"id": f"eq.{generation_id}"},
            json={"placement": placement, "confidence_state": "manually-verified"},
            headers={"Prefer": "return=representation"},
        )
        if not rows:
            raise PersistenceError(
                "apply_correction", f"update of {generation_id!r} returned no row"
            )
        return self._to_model(rows[0])
