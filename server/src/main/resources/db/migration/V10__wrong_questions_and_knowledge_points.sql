CREATE TABLE learning_knowledge_points (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    name VARCHAR(160) NOT NULL,
    normalized_name VARCHAR(160) NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_knowledge_point_owner (user_id, course_id, normalized_name),
    KEY ix_knowledge_point_course (user_id, course_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_question_knowledge_points (
    question_id VARCHAR(64) NOT NULL,
    knowledge_point_id BIGINT NOT NULL,
    PRIMARY KEY (question_id, knowledge_point_id),
    KEY ix_question_knowledge_point (knowledge_point_id, question_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_wrong_questions (
    user_id BIGINT NOT NULL,
    course_id BIGINT NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    wrong_count INT NOT NULL DEFAULT 0,
    correct_streak INT NOT NULL DEFAULT 0,
    status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
    last_wrong_answer_json TEXT NULL,
    first_wrong_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    last_practiced_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    mastered_at TIMESTAMP(3) NULL,
    PRIMARY KEY (user_id, course_id, question_id),
    KEY ix_wrong_owner_status (user_id, course_id, status, last_practiced_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
