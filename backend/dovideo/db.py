from contextlib import contextmanager
from sqlalchemy.orm import Session

@contextmanager
def session_scope(engine):
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
