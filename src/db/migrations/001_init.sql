-- 001_init.sql：v1 基线 schema（幂等，全新库与存量库均可执行）
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    modified_time REAL NOT NULL,
    md5 TEXT NOT NULL,
    added_time REAL NOT NULL,
    thumbnail_path TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified_time);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS file_tags (
    file_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (file_id, tag_id),
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id ON file_tags(tag_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO settings (key, value) VALUES ('page_size', '50');
