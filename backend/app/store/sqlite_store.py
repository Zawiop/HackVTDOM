"""Local SQLite backend.

Mirrors the Postgres schema in sql/001_generations.sql exactly, so the app and
its tests run end-to-end with no Supabase project. Selected automatically when
SUPABASE_URL is unset. Switching to Supabase is one env var, no code change.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Correction, Generation, GenerationCreate
from .errors import NotFoundError, PersistenceError

_SCHEMA = """
create table if not exists generations (
  rowid_seq        integer primary key autoincrement,
  id               text not null unique,
  address          text not null,
  lat              real not null,
  lng              real not null,
  source_photo     text,
  artifact         text,
  placement        text not null default '{}',
  mesh_url         text,
  world_state      text,
  confidence_state text not null default 'auto-low'
      check (confidence_state in ('auto-high','auto-low','manually-verified')),
  propagated_from  text,
  created_at       text not null
);
-- deliberately NOT unique on address: one address holds a sequence of rows
create index if not exists generations_address_created_idx
  on generations (address, created_at asc);
create index if not exists generations_lat_lng_idx on generations (lat, lng);
"""

_COLUMNS = (
    "id", "address", "lat", "lng", "source_photo", "artifact", "placement",
    "mesh_url", "world_state", "confidence_state", "propagated_from", "created_at",
)


class SqliteStore:
    backend_name = "sqlite"

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._conn() as c:
                c.executescript(_SCHEMA)
        except sqlite3.Error as e:
            raise PersistenceError("schema-init", str(e)) from e

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> Generation:
        d: dict[str, Any] = {k: row[k] for k in _COLUMNS}
        d["placement"] = json.loads(d["placement"] or "{}")
        return Generation(**d)

    def health(self) -> dict:
        try:
            with self._conn() as c:
                n = c.execute("select count(*) as n from generations").fetchone()["n"]
            return {"backend": self.backend_name, "ok": True, "path": str(self.path), "rows": n}
        except sqlite3.Error as e:
            raise PersistenceError("health", str(e)) from e

    def save_generation(self, payload: GenerationCreate) -> Generation:
        new_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        record = {
            "id": new_id,
            "address": payload.address,
            "lat": payload.lat,
            "lng": payload.lng,
            "source_photo": payload.source_photo,
            "artifact": payload.artifact,
            "placement": json.dumps(payload.placement.model_dump()),
            "mesh_url": payload.mesh_url,
            "world_state": payload.world_state,
            "confidence_state": payload.resolved_confidence_state(),
            "propagated_from": payload.propagated_from,
            "created_at": created_at,
        }
        cols = ", ".join(_COLUMNS)
        marks = ", ".join(f":{c}" for c in _COLUMNS)
        try:
            with self._conn() as c:
                c.execute(f"insert into generations ({cols}) values ({marks})", record)
        except sqlite3.Error as e:
            raise PersistenceError("save_generation", f"{e} (address={payload.address!r})") from e
        return self.get_generation(new_id)

    def get_generation(self, generation_id: str) -> Generation:
        try:
            with self._conn() as c:
                row = c.execute(
                    "select * from generations where id = ?", (generation_id,)
                ).fetchone()
        except sqlite3.Error as e:
            raise PersistenceError("get_generation", str(e)) from e
        if row is None:
            raise NotFoundError("get_generation", f"no generation with id {generation_id!r}")
        return self._row_to_model(row)

    def list_generations(self) -> list[Generation]:
        try:
            with self._conn() as c:
                rows = c.execute(
                    "select * from generations order by created_at asc, rowid_seq asc"
                ).fetchall()
        except sqlite3.Error as e:
            raise PersistenceError("list_generations", str(e)) from e
        return [self._row_to_model(r) for r in rows]

    def get_history_for_address(self, address: str) -> list[Generation]:
        try:
            with self._conn() as c:
                rows = c.execute(
                    "select * from generations where address = ? "
                    "order by created_at asc, rowid_seq asc",
                    (address,),
                ).fetchall()
        except sqlite3.Error as e:
            raise PersistenceError("get_history_for_address", str(e)) from e
        return [self._row_to_model(r) for r in rows]

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
        try:
            with self._conn() as c:
                c.execute(
                    "update generations set placement = ?, confidence_state = ? where id = ?",
                    (json.dumps(placement), "manually-verified", generation_id),
                )
        except sqlite3.Error as e:
            raise PersistenceError("apply_correction", str(e)) from e
        return self.get_generation(generation_id)

    def delete_generation(self, generation_id: str) -> None:
        self.get_generation(generation_id)  # raises NotFoundError if absent
        try:
            with self._conn() as c:
                c.execute("delete from generations where id = ?", (generation_id,))
        except sqlite3.Error as e:
            raise PersistenceError("delete_generation", str(e)) from e

    def delete_by_address(self, address: str) -> int:
        try:
            with self._conn() as c:
                cur = c.execute("delete from generations where address = ?", (address,))
                return cur.rowcount or 0
        except sqlite3.Error as e:
            raise PersistenceError("delete_by_address", str(e)) from e
