-- MailMind GBrain Schema (SQLite version)
-- 基于 GBrain 架构：pages + links + entities

-- 页面表：存储邮件、文档等
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'email',
    content TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    
    -- Gate 分流字段
    gate_class TEXT DEFAULT 'routine',
    gate_score REAL DEFAULT 0.5,
    
    -- 向量嵌入（存储为 BLOB，768维 float32）
    embedding BLOB,
    
    -- 时间戳
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    
    -- 唯一标识
    external_id TEXT UNIQUE
);

-- 链接表：存储实体关系
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT,
    
    -- 链接类型
    relation TEXT NOT NULL,
    
    -- 链接属性
    weight REAL DEFAULT 1.0,
    metadata TEXT DEFAULT '{}',
    
    -- 来源层级
    tier INTEGER DEFAULT 1,
    
    created_at TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (source_id) REFERENCES pages(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES pages(id) ON DELETE SET NULL,
    UNIQUE(source_id, target_id, relation)
);

-- 实体表：存储人、组织、项目等
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    
    -- 实体对齐
    canonical_id TEXT,
    merged_from TEXT DEFAULT '[]',
    
    -- 属性
    attributes TEXT DEFAULT '{}',
    
    -- compiled_truth
    truth_summary TEXT,
    truth_updated_at TEXT,
    
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    
    FOREIGN KEY (canonical_id) REFERENCES entities(id) ON DELETE SET NULL,
    UNIQUE(type, name)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_pages_type ON pages(type);
CREATE INDEX IF NOT EXISTS idx_pages_gate_class ON pages(gate_class);
CREATE INDEX IF NOT EXISTS idx_pages_created_at ON pages(created_at);
CREATE INDEX IF NOT EXISTS idx_pages_external_id ON pages(external_id);

CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
CREATE INDEX IF NOT EXISTS idx_links_relation ON links(relation);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical_id);

-- 全文搜索（简单版本，后续可升级为 FTS5）
-- SQLite 内置 LIKE 搜索，对于 MVP 阶段够用
