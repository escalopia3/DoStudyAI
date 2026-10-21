-- Java-owned durable requests and delivery outbox. Python owns ai_* tables only.
ALTER TABLE learning_resources ADD COLUMN parsing_job_id VARCHAR(64) NULL;
CREATE TABLE learning_parse_jobs (
    id VARCHAR(64) PRIMARY KEY,
    resource_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    source_revision VARCHAR(64) NOT NULL,
    source_type VARCHAR(16) NOT NULL,
    video_context LONGTEXT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
    sequence_no INT NOT NULL DEFAULT 0,
    artifact_prefix VARCHAR(512) NULL,
    error_code VARCHAR(64) NULL,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    KEY ix_parse_revision (resource_id, source_revision, created_at),
    KEY ix_parse_owner (user_id, resource_id),
    KEY ix_parse_state (state, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_parse_outbox (
    job_id VARCHAR(64) PRIMARY KEY,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY ix_parse_delivery (delivered, next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
