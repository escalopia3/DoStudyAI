"""Import a reviewed, read-only archive of legacy conversations and attempts."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, Field, AwareDatetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.legacy_courses import NAMESPACE, legacy_id
from dovideo.config import Settings
from dovideo.models import Course, LegacyStudyRecord


class Entry(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=200000)


class Record(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    course_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    kind: Literal["conversation", "practice"]
    title: str = Field(min_length=1, max_length=200)
    occurred_at: AwareDatetime
    entries: list[Entry] = Field(min_length=1, max_length=1000)


class Manifest(BaseModel):
    source: str = Field(pattern=r"^[^/]+$", min_length=1, max_length=100)
    owner_map: dict[int, UUID]
    records: list[Record]


def import_history(session, manifest):
    seen = set()
    inserted = 0
    for record in manifest.records:
        course_id = legacy_id(manifest.source, "course", record.course_id)
        course = session.get(Course, course_id)
        if course is None or manifest.owner_map.get(record.user_id) != course.created_by:
            raise ValueError("unmapped or mismatched course owner")
        record_id = uuid5(NAMESPACE, f"{manifest.source}/history/{record.kind}/{record.id}")
        if record_id in seen:
            raise ValueError("duplicate legacy history record")
        seen.add(record_id)
        values = dict(course_id=course_id, kind=record.kind, title=record.title,
                      payload={"entries": [entry.model_dump() for entry in record.entries]},
                      occurred_at=record.occurred_at)
        existing = session.get(LegacyStudyRecord, record_id)
        if existing is None:
            session.add(LegacyStudyRecord(id=record_id, **values))
            inserted += 1
        elif any(getattr(existing, key) != value for key, value in values.items()):
            raise ValueError(f"history record conflicts with existing archive: {record_id}")
    session.flush()
    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest = Manifest.model_validate_json(args.manifest.read_bytes())
    engine = create_engine(Settings.from_env().database_url)
    try:
        with Session(engine) as session:
            inserted = import_history(session, manifest)
            if args.apply:
                session.commit()
            else:
                session.rollback()
        print(json.dumps({"applied": args.apply, "inserted": inserted, "unchanged": len(manifest.records)-inserted}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
