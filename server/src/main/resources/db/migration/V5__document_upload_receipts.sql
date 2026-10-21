-- Request fingerprint binds an upload receipt to its content and destination.
-- Older V4 receipts deliberately remain NULL and cannot be silently reused.
ALTER TABLE learning_resources ADD COLUMN request_fingerprint CHAR(64) NULL;
