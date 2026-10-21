ALTER TABLE learning_message_citations
    ADD COLUMN source_id VARCHAR(16) NOT NULL AFTER ordinal_no;
