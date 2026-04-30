-- MailMind GBrain Schema
-- 基于 GBrain 架构：pages + links + entities

-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 页面表：存储邮件、文档等
CREATE TABLE IF NOT EXISTS pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(50) NOT NULL DEFAULT 'email',  -- email, document, attachment
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    
    -- Gate 分流字段
    gate_class VARCHAR(20) DEFAULT 'routine',   -- urgent, important, routine, notification, spam
    gate_score FLOAT DEFAULT 0.5,
    
    -- 向量嵌入（768维，bge-small-zh）
    embedding vector(768),
    
    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 唯一标识（邮件用 message_id）
    external_id VARCHAR(255) UNIQUE,
    
    -- 全文搜索
    search_vector tsvector
);

-- 链接表：存储实体关系
CREATE TABLE IF NOT EXISTS links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    target_id UUID REFERENCES pages(id) ON DELETE SET NULL,
    
    -- 链接类型
    relation VARCHAR(100) NOT NULL,  -- sent_to, cc'd, mentions, replied_to, etc.
    
    -- 链接属性
    weight FLOAT DEFAULT 1.0,
    metadata JSONB DEFAULT '{}',
    
    -- 来源层级
    tier INT DEFAULT 1,  -- 1=header, 2=body, 4=llm
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(source_id, target_id, relation)
);

-- 实体表：存储人、组织、项目等
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(50) NOT NULL,  -- person, organization, project, topic
    name VARCHAR(500) NOT NULL,
    
    -- 实体对齐
    canonical_id UUID REFERENCES entities(id) ON DELETE SET NULL,
    merged_from UUID[] DEFAULT '{}',
    
    -- 属性
    attributes JSONB DEFAULT '{}',
    
    -- compiled_truth
    truth_summary TEXT,
    truth_updated_at TIMESTAMPTZ,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(type, name)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_pages_type ON pages(type);
CREATE INDEX IF NOT EXISTS idx_pages_gate_class ON pages(gate_class);
CREATE INDEX IF NOT EXISTS idx_pages_created_at ON pages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pages_external_id ON pages(external_id);
CREATE INDEX IF NOT EXISTS idx_pages_search_vector ON pages USING gin(search_vector);

-- 向量索引（HNSW）
CREATE INDEX IF NOT EXISTS idx_pages_embedding ON pages USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
CREATE INDEX IF NOT EXISTS idx_links_relation ON links(relation);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical_id);

-- 触发器：自动更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER pages_updated_at
    BEFORE UPDATE ON pages
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER entities_updated_at
    BEFORE UPDATE ON entities
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 全文搜索触发器
CREATE OR REPLACE FUNCTION pages_search_trigger()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector = 
        setweight(to_tsvector('english', COALESCE(NEW.metadata->>'subject', '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER pages_search_update
    BEFORE INSERT OR UPDATE ON pages
    FOR EACH ROW
    EXECUTE FUNCTION pages_search_trigger();
