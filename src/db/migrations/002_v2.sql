-- 002_v2.sql：升级到 v2 schema（见开发手册 4.2，每库只执行一次）

-- files 增列
ALTER TABLE files ADD COLUMN file_type TEXT DEFAULT 'other';
ALTER TABLE files ADD COLUMN md5_state INTEGER DEFAULT 0;
ALTER TABLE files ADD COLUMN missing INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_files_file_type ON files(file_type);

-- 媒体元数据（一对一）
CREATE TABLE IF NOT EXISTS file_meta (
    file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    width INTEGER,
    height INTEGER,
    duration_sec REAL,
    page_count INTEGER,
    shot_time TEXT,
    camera TEXT,
    extra_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_meta_shot_time ON file_meta(shot_time);

-- 标签增强
ALTER TABLE tags ADD COLUMN color TEXT;
ALTER TABLE tags ADD COLUMN is_auto INTEGER DEFAULT 0;
ALTER TABLE file_tags ADD COLUMN source TEXT DEFAULT 'manual';

-- 自动打标规则
CREATE TABLE IF NOT EXISTS auto_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    match_kind TEXT NOT NULL,
    pattern TEXT NOT NULL,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    enabled INTEGER DEFAULT 1
);

-- Vault 加密区
CREATE TABLE IF NOT EXISTS vault_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_path TEXT NOT NULL,
    enc_path TEXT NOT NULL,
    enc_size INTEGER NOT NULL,
    orig_size INTEGER NOT NULL,
    wrapped_dek BLOB NOT NULL,
    nonce BLOB NOT NULL,
    added_time REAL NOT NULL
);

-- 归集区记录
CREATE TABLE IF NOT EXISTS consolidated_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    link_path TEXT NOT NULL UNIQUE,
    created_time REAL NOT NULL
);
