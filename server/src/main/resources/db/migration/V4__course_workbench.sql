CREATE TABLE courses (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    semester VARCHAR(50) NOT NULL DEFAULT '',
    description VARCHAR(1000) NOT NULL DEFAULT '',
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_courses_owner (user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE course_chapters (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    course_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    KEY idx_chapters_course (course_id, sort_order, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE learning_resources (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    type VARCHAR(16) NOT NULL,
    media_id BIGINT NULL,
    filename VARCHAR(255) NOT NULL,
    object_key VARCHAR(512) NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    parse_status VARCHAR(32) NOT NULL DEFAULT 'UPLOADED',
    upload_key VARCHAR(100) NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_resource_media (media_id),
    UNIQUE KEY uk_resource_upload (user_id, upload_key),
    KEY idx_resources_owner (user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE course_resources (
    resource_id BIGINT NOT NULL PRIMARY KEY,
    course_id BIGINT NOT NULL,
    chapter_id BIGINT NULL,
    KEY idx_course_resources (course_id, chapter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
