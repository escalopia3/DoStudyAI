from alembic import context
from agent_service.config import Settings
from agent_service.store import Store, metadata
import agent_service.learning_agent.persistence  # register agent tables in shared metadata

engine = Store(Settings.from_env().database_url).engine
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata, version_table="ai_alembic_version")
    with context.begin_transaction():
        context.run_migrations()
