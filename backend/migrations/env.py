import os
from alembic import context
from sqlalchemy import create_engine, pool
from dovideo.config import load_local_environment

load_local_environment()
url = os.environ["DOVIDEO_DATABASE_URL"]
if not url.startswith("postgresql+psycopg://"):
    raise ValueError("Only the isolated PostgreSQL v2 database is supported")
if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
