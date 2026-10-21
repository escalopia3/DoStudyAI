from __future__ import annotations

import json
import time
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, Float,
                        create_engine, select, update)


metadata = MetaData()
indexes = Table("ai_knowledge_indexes", metadata,
    Column("index_revision", String(64), primary_key=True),
    Column("resource_id", String(64), nullable=False),
    Column("source_revision", String(100), nullable=False),
    Column("embedding_version", String(255), nullable=False),
    Column("state", String(20), nullable=False),
    Column("manifest_json", Text), Column("created_at", Float, nullable=False),
    Column("published_at", Float))
active_indexes = Table("ai_active_knowledge_indexes", metadata,
    Column("resource_id", String(64), primary_key=True),
    Column("source_revision", String(100), nullable=False),
    Column("index_revision", String(64), nullable=False),
    Column("generation", Integer, nullable=False), Column("updated_at", Float, nullable=False))


class IndexStore:
    def __init__(self, url: str): self.engine = create_engine(url, pool_pre_ping=True)

    def begin(self, resource_id: str, source_revision: str, index_revision: str,
              embedding_version: str) -> None:
        row = dict(index_revision=index_revision, resource_id=resource_id,
                   source_revision=source_revision, embedding_version=embedding_version,
                   state="BUILDING", manifest_json=None, created_at=time.time(), published_at=None)
        with self.engine.begin() as db:
            existing = db.execute(select(indexes).where(indexes.c.index_revision == index_revision)).mappings().first()
            if existing:
                for key in ("resource_id", "source_revision", "embedding_version"):
                    if existing[key] != row[key]: raise ValueError("INDEX_REVISION_CONFLICT")
            else: db.execute(indexes.insert().values(**row))

    def mark_verified(self, index_revision: str, manifest: dict) -> None:
        with self.engine.begin() as db:
            changed = db.execute(update(indexes).where(indexes.c.index_revision == index_revision,
                indexes.c.state.in_(["BUILDING", "VERIFIED"])).values(
                    state="VERIFIED", manifest_json=json.dumps(manifest, ensure_ascii=False))).rowcount
            if changed != 1: raise ValueError("INDEX_NOT_BUILDING")

    def publish(self, resource_id: str, source_revision: str, index_revision: str,
                expected_previous: str | None = None) -> int:
        now = time.time()
        with self.engine.begin() as db:
            target = db.execute(select(indexes).where(
                indexes.c.index_revision == index_revision).with_for_update()).mappings().first()
            if not target or target["state"] not in ("VERIFIED", "PUBLISHED"):
                raise ValueError("INDEX_NOT_VERIFIED")
            if target["resource_id"] != resource_id or target["source_revision"] != source_revision:
                raise ValueError("INDEX_SOURCE_CHANGED")
            active = db.execute(select(active_indexes).where(
                active_indexes.c.resource_id == resource_id).with_for_update()).mappings().first()
            if active and active["source_revision"] == source_revision and active["index_revision"] == index_revision:
                return int(active["generation"])
            actual_previous = active["index_revision"] if active else None
            if actual_previous != expected_previous: raise ValueError("ACTIVE_INDEX_CAS_FAILED")
            generation = int(active["generation"] + 1) if active else 1
            values = dict(source_revision=source_revision, index_revision=index_revision,
                          generation=generation, updated_at=now)
            if active:
                db.execute(update(active_indexes).where(active_indexes.c.resource_id == resource_id).values(**values))
            else:
                db.execute(active_indexes.insert().values(resource_id=resource_id, **values))
            db.execute(update(indexes).where(indexes.c.index_revision == index_revision)
                       .values(state="PUBLISHED", published_at=now))
            return generation

    def active(self, resource_ids: list[str]) -> list[dict]:
        if not resource_ids: return []
        with self.engine.connect() as db:
            return [dict(x) for x in db.execute(select(active_indexes).where(
                active_indexes.c.resource_id.in_(resource_ids))).mappings()]

