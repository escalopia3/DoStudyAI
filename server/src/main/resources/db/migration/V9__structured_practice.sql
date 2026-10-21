CREATE TABLE learning_practice_sets (
    id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    assistant_message_id VARCHAR(64) NOT NULL,
    title VARCHAR(200) NOT NULL,
    request_text TEXT NOT NULL,
    instructions TEXT NOT NULL,
    knowledge_snapshot_id VARCHAR(80) NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_practice_message (assistant_message_id),
    KEY ix_practice_owner (user_id, course_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_questions (
    id VARCHAR(64) PRIMARY KEY,
    practice_set_id VARCHAR(64) NOT NULL,
    ordinal_no INT NOT NULL,
    question_type VARCHAR(24) NOT NULL,
    stem TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_answers_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    rubric_keywords_json TEXT NOT NULL,
    difficulty VARCHAR(16) NOT NULL,
    points INT NOT NULL,
    knowledge_points_json TEXT NOT NULL,
    citation_ids_json TEXT NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_practice_question_ordinal (practice_set_id, ordinal_no),
    KEY ix_question_practice (practice_set_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_attempts (
    id VARCHAR(64) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    practice_set_id VARCHAR(64) NOT NULL,
    state VARCHAR(24) NOT NULL,
    score DECIMAL(8,2) NOT NULL DEFAULT 0,
    max_score DECIMAL(8,2) NOT NULL DEFAULT 0,
    started_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    submitted_at TIMESTAMP(3) NULL,
    KEY ix_attempt_owner (user_id, course_id, submitted_at),
    KEY ix_attempt_practice (practice_set_id, submitted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_answers (
    id VARCHAR(64) PRIMARY KEY,
    attempt_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    answer_json TEXT NOT NULL,
    is_correct TINYINT(1) NOT NULL,
    score DECIMAL(8,2) NOT NULL,
    max_score DECIMAL(8,2) NOT NULL,
    feedback TEXT NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_attempt_question (attempt_id, question_id),
    KEY ix_answer_question (question_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
