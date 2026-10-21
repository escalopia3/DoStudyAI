CREATE TABLE learning_memory_items (
    id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    memory_type VARCHAR(32) NOT NULL,
    content VARCHAR(1000) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_ref VARCHAR(100) NULL,
    confidence DECIMAL(5,4) NOT NULL DEFAULT 1.0000,
    status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
    user_confirmed TINYINT(1) NOT NULL DEFAULT 0,
    expires_at TIMESTAMP(3) NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    KEY ix_memory_owner (user_id, course_id, status, updated_at),
    KEY ix_memory_source (user_id, course_id, memory_type, source_type, source_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_memory_events (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    memory_id VARCHAR(64) NOT NULL,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    action VARCHAR(24) NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY ix_memory_event_item (memory_id, created_at),
    KEY ix_memory_event_owner (user_id, course_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
