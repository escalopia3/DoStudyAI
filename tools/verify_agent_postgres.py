"""Provision a new isolated test DB, migrate it, test recovery, then drop only that DB."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def main():
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from dovideo.config import Settings
    from alembic.config import Config
    from alembic import command
    settings=Settings.from_env()
    source=make_url(settings.database_url)
    name='agent_eng_'+uuid.uuid4().hex+'_test'
    target=source.set(database=name)
    engine=create_engine(source,isolation_level='AUTOCOMMIT',connect_args={'connect_timeout':3})
    created=False
    out=ROOT/'outputs/agent-engineering-20261106'
    out.mkdir(parents=True,exist_ok=True)
    try:
        with engine.connect() as c:
            c.execute(text('CREATE DATABASE '+engine.dialect.identifier_preparer.quote(name)))
            created=True
        os.environ['DOVIDEO_DATABASE_URL']=target.render_as_string(hide_password=False)
        os.environ['DOVIDEO_MINIO_BUCKET']='agent-engineering-test'
        os.environ['DOVIDEO_AGENT_PG_TEST']='1'
        os.environ['PYTHONPATH']=str(ROOT/'backend')
        command.upgrade(Config(str(ROOT/'backend/alembic.ini')),'head')
        result=subprocess.run([sys.executable,'-m','pytest','backend/tests/test_agent_recovery_postgres.py',
            '-q','-p','no:cacheprovider','--junitxml='+str(out/'postgres-tests.xml')],cwd=ROOT)
        roundtrip=False
        if result.returncode==0:
            # Exercise downgrade/upgrade only inside this script's new test DB.
            command.downgrade(Config(str(ROOT/'backend/alembic.ini')),'0011')
            command.upgrade(Config(str(ROOT/'backend/alembic.ini')),'head')
            roundtrip=True
        (out/'postgres-verification.json').write_text(json.dumps({'isolated_database':name,
            'migration':'0012','migration_roundtrip_passed':roundtrip,
            'test_exit_code':result.returncode,'production_schema_modified':False}),encoding='utf-8')
        return result.returncode
    except Exception as exc:
        (out/'postgres-verification.json').write_text(json.dumps({'error_type':type(exc).__name__,
            'created':created,'production_schema_modified':False}),encoding='utf-8')
        print('ISOLATED_POSTGRES_VERIFICATION_FAILED '+type(exc).__name__)
        return 2
    finally:
        # The name is generated here and CREATE must have succeeded; never accept
        # an existing database or a user-supplied deletion target.
        if created:
            assert name.startswith('agent_eng_') and name.endswith('_test') and name!=source.database
            with engine.connect() as c:
                c.execute(text('DROP DATABASE '+engine.dialect.identifier_preparer.quote(name)+' WITH (FORCE)'))
        engine.dispose()


if __name__=='__main__':raise SystemExit(main())
