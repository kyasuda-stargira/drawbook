-- Encrypted notice content, split into pieces under D1's row size limit (used instead of R2).
CREATE TABLE blob_chunks (notice_id TEXT NOT NULL, seq INTEGER NOT NULL, data BLOB NOT NULL, PRIMARY KEY (notice_id, seq));
