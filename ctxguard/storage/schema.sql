-- SQLite Schema for CtxGuard persistence

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project_name TEXT DEFAULT 'default',
    prompt_preview TEXT DEFAULT '',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    protocol TEXT NOT NULL,
    model TEXT NOT NULL,
    raw_tokens INTEGER NOT NULL,
    optimized_tokens INTEGER NOT NULL,
    saved_tokens INTEGER NOT NULL,
    saved_ratio REAL NOT NULL,
    latency_ms REAL NOT NULL,
    applied_compressors TEXT DEFAULT '[]',
    cached_tokens INTEGER DEFAULT 0,
    cache_type TEXT DEFAULT 'none',
    status TEXT DEFAULT 'completed',
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS fingerprints (
    hash_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    char_length INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_requests_session ON requests(session_id);
CREATE INDEX IF NOT EXISTS idx_requests_project ON requests(project_name);
CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp);
CREATE INDEX IF NOT EXISTS idx_fingerprints_session ON fingerprints(session_id);

-- Knowledge Graph (Entities & Relationships)
CREATE TABLE IF NOT EXISTS kg_entities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default_user',
    name TEXT NOT NULL,
    name_lower TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'concept',
    description TEXT,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS kg_relationships (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default_user',
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'related_to',
    weight REAL NOT NULL DEFAULT 1.0,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (source_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES kg_entities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kg_entities_user ON kg_entities(user_id);
CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(user_id, name_lower);
CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_kg_rel_source ON kg_relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_rel_target ON kg_relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_kg_rel_type ON kg_relationships(relation_type);
CREATE INDEX IF NOT EXISTS idx_kg_rel_user ON kg_relationships(user_id);
