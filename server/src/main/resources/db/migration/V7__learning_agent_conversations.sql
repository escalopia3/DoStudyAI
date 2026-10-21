CREATE TABLE learning_conversations (
    id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    KEY ix_conversation_owner (user_id, course_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_messages (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL,
    role VARCHAR(16) NOT NULL,
    mode VARCHAR(24) NOT NULL,
    content LONGTEXT NOT NULL,
    status VARCHAR(24) NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY ix_messages_conversation (conversation_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_agent_runs (
    id VARCHAR(64) PRIMARY KEY,
    conversation_id VARCHAR(64) NOT NULL,
    user_message_id VARCHAR(64) NOT NULL,
    assistant_message_id VARCHAR(64) NOT NULL,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    state VARCHAR(24) NOT NULL,
    sequence_no INT NOT NULL DEFAULT 0,
    authorized_resources_json TEXT NOT NULL,
    knowledge_snapshot_id VARCHAR(80) NULL,
    model VARCHAR(200) NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    error_code VARCHAR(64) NULL,
    deadline_at TIMESTAMP(3) NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    completed_at TIMESTAMP(3) NULL,
    KEY ix_agent_run_owner (user_id, course_id, created_at),
    KEY ix_agent_run_state (state, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_message_citations (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    message_id VARCHAR(64) NOT NULL,
    ordinal_no INT NOT NULL,
    resource_id BIGINT NOT NULL,
    index_revision VARCHAR(64) NOT NULL,
    chunk_id VARCHAR(80) NOT NULL,
    parent_id VARCHAR(80) NULL,
    content_hash VARCHAR(64) NOT NULL,
    title_path_json TEXT NOT NULL,
    locator_json LONGTEXT NOT NULL,
    quote_text TEXT NOT NULL,
    UNIQUE KEY uk_message_citation (message_id, ordinal_no),
    KEY ix_citation_resource (resource_id, index_revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
