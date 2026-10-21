CREATE TABLE learning_mastery_states (
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    knowledge_point_id BIGINT NOT NULL,
    mastery_score DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
    confidence_count INT NOT NULL DEFAULT 0,
    correct_count INT NOT NULL DEFAULT 0,
    wrong_count INT NOT NULL DEFAULT 0,
    last_practiced_at TIMESTAMP(3) NULL,
    updated_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (user_id, course_id, knowledge_point_id),
    KEY ix_mastery_owner_score (user_id, course_id, mastery_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_mastery_events (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    knowledge_point_id BIGINT NOT NULL,
    attempt_id VARCHAR(64) NULL,
    question_id VARCHAR(64) NULL,
    event_type VARCHAR(32) NOT NULL,
    delta_value DECIMAL(6,4) NOT NULL,
    score_after DECIMAL(5,4) NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY ix_mastery_event_owner (user_id, course_id, created_at),
    KEY ix_mastery_event_point (knowledge_point_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
