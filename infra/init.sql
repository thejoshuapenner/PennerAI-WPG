-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Ingestion Ledger Table
CREATE TABLE IF NOT EXISTS ingestion_ledger (
    id SERIAL PRIMARY KEY,
    jurisdiction_name VARCHAR(255) NOT NULL,
    entity_type VARCHAR(255) NOT NULL,
    state VARCHAR(10) DEFAULT 'WA',
    official_url TEXT,
    vendor VARCHAR(100),
    api_endpoint TEXT,
    target_start_date DATE DEFAULT '2026-01-01',
    last_scrape_attempt TIMESTAMP,
    last_scrape_status VARCHAR(50) DEFAULT 'Pending',
    documents_vaulted INTEGER DEFAULT 0,
    notes TEXT,
    CONSTRAINT idx_jurisdiction_type UNIQUE (jurisdiction_name, entity_type)
);

-- State Auditor (SAO) Findings Table
CREATE TABLE IF NOT EXISTS findings (
    report_num VARCHAR(50) PRIMARY KEY,
    jurisdiction VARCHAR(255) NOT NULL,
    type VARCHAR(100) NOT NULL,
    category VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    root_cause TEXT,
    dollar_impact BIGINT DEFAULT 0,
    embedding vector(1536) -- text-embedding-3-small dimension
);

-- HNSW Vector Index for fast semantic audit searches
CREATE INDEX IF NOT EXISTS idx_findings_embedding 
ON findings USING hnsw (embedding vector_cosine_ops);

-- Meeting Actions Table (Basic Scraped Council Actions)
CREATE TABLE IF NOT EXISTS meeting_actions (
    event_id VARCHAR(100) PRIMARY KEY,
    jurisdiction VARCHAR(255) NOT NULL,
    committee VARCHAR(255),
    meeting_date DATE,
    key_action TEXT NOT NULL,
    dollar_amount BIGINT DEFAULT 0,
    vote_outcome VARCHAR(100)
);

-- Merged Actions Table (Synthesized Council Actions)
CREATE TABLE IF NOT EXISTS merged_actions (
    event_id VARCHAR(100) PRIMARY KEY,
    jurisdiction VARCHAR(255) NOT NULL,
    committee VARCHAR(255),
    meeting_date DATE,
    key_action TEXT NOT NULL,
    vendor VARCHAR(255),
    dollar_amount BIGINT DEFAULT 0,
    vote_outcome VARCHAR(100),
    embedding vector(1536)
);

-- HNSW Index for merged actions
CREATE INDEX IF NOT EXISTS idx_merged_actions_embedding 
ON merged_actions USING hnsw (embedding vector_cosine_ops);

-- Raw Civic Scraper Files Tracker Table
CREATE TABLE IF NOT EXISTS raw_civic_scraper_files (
    id VARCHAR(100) PRIMARY KEY,
    jurisdiction VARCHAR(255) NOT NULL,
    file_url TEXT NOT NULL,
    file_type VARCHAR(50),
    local_path TEXT,
    processed INTEGER DEFAULT 0
);

-- Processed Intent Table (Granular Council / School Board Agenda Items)
CREATE TABLE IF NOT EXISTS processed_intent (
    id SERIAL PRIMARY KEY,
    file_id VARCHAR(255) NOT NULL,
    jurisdiction VARCHAR(255) NOT NULL,
    meeting_date DATE,
    event_id VARCHAR(100),
    doc_type VARCHAR(50),
    item_number VARCHAR(50),
    agenda_item_title TEXT NOT NULL,
    key_action TEXT NOT NULL,
    vendor VARCHAR(255),
    dollar_amount BIGINT DEFAULT 0,
    vote_outcome VARCHAR(100),
    primary_entity VARCHAR(255),
    embedding vector(1536)
);

-- HNSW Index for processed intents
CREATE INDEX IF NOT EXISTS idx_processed_intent_embedding 
ON processed_intent USING hnsw (embedding vector_cosine_ops);

-- Alert Subscriptions Table (Lead Capture)
CREATE TABLE IF NOT EXISTS alert_subscriptions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    topics TEXT NOT NULL,
    jurisdiction VARCHAR(255),
    query TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
