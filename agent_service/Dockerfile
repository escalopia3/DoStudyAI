FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml alembic.ini ./
COPY agent_service ./agent_service
COPY knowledge_service ./knowledge_service
RUN pip install --no-cache-dir ".[indexing,agent]" && useradd -m -u 10001 learning && mkdir /work && chown learning /work
USER learning
ENV LEARNING_WORK_DIR=/work HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
CMD ["uvicorn", "agent_service.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8091"]
