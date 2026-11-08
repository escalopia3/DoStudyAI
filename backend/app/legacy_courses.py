"""Validate and import a reviewed course/chapter export into v2."""
import argparse
import json
import uuid
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from dovideo.config import Settings
from dovideo.models import User, Course, CourseChapter

NAMESPACE=uuid.UUID('57e6c667-79c9-48cb-bf20-5599b75db265')

def legacy_id(source,table,id_):
    if type(id_) is not int or id_<=0:
        raise ValueError(f'invalid legacy {table} id')
    return uuid.uuid5(NAMESPACE,f'{source}/{table}/{id_}')

def import_courses(session,manifest):
    source=manifest['source']
    if not isinstance(source,str) or not source.strip() or '/' in source:
        raise ValueError('invalid source identifier')
    owners={}
    for key,value in manifest['owner_map'].items():
        account=session.get(User,uuid.UUID(value))
        if account is None:raise ValueError(f'owner mapping {key} does not exist')
        if account.id in owners.values():raise ValueError('owner mapping must be one-to-one')
        owners[int(key)]=account.id
    course_ids,chapter_ids,slots=set(),set(),set()
    counts={'courses':0,'chapters':0,'unchanged':0}
    def upsert(cls,id_,values,kind):
        row=session.get(cls,id_)
        if row is None:
            session.add(cls(id=id_,**values))
            counts[kind]+=1
        elif any(getattr(row,k)!=v for k,v in values.items()):
            raise ValueError(f'{kind} target conflicts: {id_}')
        else:counts['unchanged']+=1
    for course in manifest['courses']:
        id_=legacy_id(source,'course',course['id'])
        if id_ in course_ids:raise ValueError('duplicate course')
        course_ids.add(id_)
        if course['user_id'] not in owners:raise ValueError('unmapped course owner')
        upsert(Course,id_,dict(created_by=owners[course['user_id']],name=course['name'],
            semester=course.get('semester',''),description=course.get('description','')),'courses')
    session.flush()
    for chapter in manifest['course_chapters']:
        id_=legacy_id(source,'chapter',chapter['id'])
        course_id=legacy_id(source,'course',chapter['course_id'])
        slot=(course_id,chapter['sort_order'])
        if id_ in chapter_ids or slot in slots or course_id not in course_ids:
            raise ValueError('invalid chapter ownership or duplicate order')
        chapter_ids.add(id_);slots.add(slot)
        upsert(CourseChapter,id_,dict(course_id=course_id,name=chapter['name'],
            sort_order=chapter['sort_order']),'chapters')
    session.flush()
    return counts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--apply',action='store_true',help='commit changes; default is validation followed by rollback')
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    engine=create_engine(Settings.from_env().database_url)
    try:
        with Session(engine) as session:
            counts=import_courses(session,manifest)
            if args.apply:session.commit()
            else:session.rollback()
        print(json.dumps({'applied':args.apply,**counts}))
    finally:
        engine.dispose()

if __name__=='__main__':main()
