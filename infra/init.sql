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
    year INTEGER,
    embedding vector(1536), -- text-embedding-3-small dimension
    source_url TEXT
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
    anonymous_user_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW()
);

-- API Keys Table for Agent API Access
CREATE TABLE IF NOT EXISTS api_keys (
    key_id SERIAL PRIMARY KEY,
    api_key VARCHAR(255) UNIQUE NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- API Usage Logs Table for Agent API Cost/Usage tracking
CREATE TABLE IF NOT EXISTS api_usage_logs (
    id SERIAL PRIMARY KEY,
    api_key VARCHAR(255) REFERENCES api_keys(api_key) ON DELETE CASCADE,
    endpoint VARCHAR(100) NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    estimated_cost NUMERIC(10, 6) DEFAULT 0.0,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Usage Events Table
CREATE TABLE IF NOT EXISTS usage_events (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    hashed_ip VARCHAR(64) NOT NULL,
    anonymous_user_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    message_count_in_session INTEGER DEFAULT 1,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    endpoint VARCHAR(100) NOT NULL,
    response_time_ms INTEGER DEFAULT 0,
    has_citations BOOLEAN DEFAULT FALSE,
    has_correlations BOOLEAN DEFAULT FALSE,
    agent_api_key VARCHAR(255) REFERENCES api_keys(api_key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_events_timestamp ON usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_events_anon_user ON usage_events(anonymous_user_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_session ON usage_events(session_id);

-- Daily Aggregated Metrics Table (For Dashboards)
CREATE TABLE IF NOT EXISTS daily_usage_aggregates (
    date DATE PRIMARY KEY,
    dau INTEGER NOT NULL,
    total_messages INTEGER NOT NULL,
    avg_messages_per_user NUMERIC(5, 2) NOT NULL,
    avg_session_depth NUMERIC(5, 2) NOT NULL,
    heavy_users_day_count INTEGER NOT NULL,
    heavy_users_total_count INTEGER NOT NULL,
    heavy_users_multi_day_count INTEGER NOT NULL,
    retention_day_2 NUMERIC(5, 2),
    retention_day_7 NUMERIC(5, 2),
    retention_day_30 NUMERIC(5, 2),
    drop_off_stats JSONB,
    popular_topics JSONB
);

-- Surfaced Insights & Correlations Table
CREATE TABLE IF NOT EXISTS correlations (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    hook TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    citations JSONB DEFAULT '[]', -- [{id, source, title, url}]
    status VARCHAR(50) DEFAULT 'proposed', -- 'proposed', 'approved', 'dismissed'
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

-- Bug Reports & Civic Tips Table
CREATE TABLE IF NOT EXISTS bug_reports (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255),
    report_type VARCHAR(50) NOT NULL, -- 'bug' or 'tip'
    description TEXT NOT NULL,
    anonymous_user_id VARCHAR(64),
    session_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Authoritative Entities directory
CREATE TABLE IF NOT EXISTS authoritative_entities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    entity_type VARCHAR(50) NOT NULL, -- 'port', 'school_district', 'city', 'county'
    official_url VARCHAR(255) NOT NULL,
    agenda_portal_url VARCHAR(255),
    platform VARCHAR(50),
    verification_status VARCHAR(50) DEFAULT 'unverified',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- PDC Political Donations
CREATE TABLE IF NOT EXISTS political_contributions (
    id SERIAL PRIMARY KEY,
    candidate_name VARCHAR(255) NOT NULL,
    contributor_name VARCHAR(255) NOT NULL,
    contributor_employer VARCHAR(255),
    amount NUMERIC(12, 2) NOT NULL,
    receipt_date DATE NOT NULL,
    jurisdiction VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- WaLeg Legislative Bills
CREATE TABLE IF NOT EXISTS legislative_bills (
    bill_number VARCHAR(50) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    biennium VARCHAR(50) NOT NULL,
    sponsor VARCHAR(255),
    passed_date DATE,
    summary TEXT,
    affected_rcws JSONB DEFAULT '[]',
    affected_wacs JSONB DEFAULT '[]',
    policy_category VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Master Jurisdictions Table
CREATE TABLE IF NOT EXISTS jurisdictions (
    name VARCHAR(255) PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL, -- 'city', 'county', 'school_district', 'port', 'special_district', 'state'
    county VARCHAR(100),
    population INTEGER,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    last_updated TIMESTAMP DEFAULT NOW()
);

-- Budgets Table (Aggregated)
CREATE TABLE IF NOT EXISTS budgets (
    id SERIAL PRIMARY KEY,
    jurisdiction_name VARCHAR(255) REFERENCES jurisdictions(name) ON DELETE CASCADE,
    entity_type VARCHAR(100) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    total_revenue NUMERIC(15, 2) NOT NULL,
    total_expenditures NUMERIC(15, 2) NOT NULL,
    fund_balance_beginning NUMERIC(15, 2),
    fund_balance_ending NUMERIC(15, 2),
    source_url TEXT,
    last_updated TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_jurisdiction_budget UNIQUE (jurisdiction_name, fiscal_year)
);

-- Budget Items Table (Granular Breakdown)
CREATE TABLE IF NOT EXISTS budget_items (
    id SERIAL PRIMARY KEY,
    budget_id INTEGER REFERENCES budgets(id) ON DELETE CASCADE,
    category_type VARCHAR(50) NOT NULL, -- 'revenue' or 'expenditure'
    major_category VARCHAR(255) NOT NULL, -- 'Public Safety', 'General Admin', etc.
    amount NUMERIC(15, 2) NOT NULL,
    account_code VARCHAR(50), -- BARS code if available
    description TEXT,
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_budget_items_embedding ON budget_items USING hnsw (embedding vector_cosine_ops);

-- Grants Table
CREATE TABLE IF NOT EXISTS grants (
    id SERIAL PRIMARY KEY,
    grant_title VARCHAR(255) NOT NULL,
    grant_id VARCHAR(100),
    awarding_agency VARCHAR(255) NOT NULL,
    recipient_jurisdiction VARCHAR(255) REFERENCES jurisdictions(name) ON DELETE SET NULL,
    recipient_entity_type VARCHAR(100),
    award_amount NUMERIC(15, 2) NOT NULL,
    award_date DATE,
    performance_period_start DATE,
    performance_period_end DATE,
    purpose_category VARCHAR(255),
    funding_source VARCHAR(100), -- 'state', 'federal'
    source_url TEXT,
    last_updated TIMESTAMP DEFAULT NOW(),
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_grants_embedding ON grants USING hnsw (embedding vector_cosine_ops);

-- School District Financials Table (OSPI Specifics)
CREATE TABLE IF NOT EXISTS school_district_financials (
    id SERIAL PRIMARY KEY,
    district_name VARCHAR(255) REFERENCES jurisdictions(name) ON DELETE CASCADE,
    fiscal_year INTEGER NOT NULL,
    enrollment NUMERIC(10, 2), -- FTE Enrollment
    total_revenue NUMERIC(15, 2) NOT NULL,
    total_expenditures NUMERIC(15, 2) NOT NULL,
    levy_amount NUMERIC(15, 2),
    special_education_spending NUMERIC(15, 2),
    federal_funding_amount NUMERIC(15, 2),
    source_url TEXT,
    last_updated TIMESTAMP DEFAULT NOW(),
    embedding vector(1536),
    CONSTRAINT unique_district_financial_year UNIQUE (district_name, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_school_financials_embedding ON school_district_financials USING hnsw (embedding vector_cosine_ops);

-- Alter existing tables for audit trails and verification metadata
ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS verbatim_text_context TEXT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS meeting_type VARCHAR(50);
ALTER TABLE findings ADD COLUMN IF NOT EXISTS verification_score NUMERIC(5, 2);
ALTER TABLE findings ADD COLUMN IF NOT EXISTS reviewer_status VARCHAR(50) DEFAULT 'unverified';

ALTER TABLE merged_actions ADD COLUMN IF NOT EXISTS verbatim_text_context TEXT;
ALTER TABLE merged_actions ADD COLUMN IF NOT EXISTS meeting_type VARCHAR(50);
ALTER TABLE merged_actions ADD COLUMN IF NOT EXISTS verification_score NUMERIC(5, 2);
ALTER TABLE merged_actions ADD COLUMN IF NOT EXISTS reviewer_status VARCHAR(50) DEFAULT 'unverified';

ALTER TABLE processed_intent ADD COLUMN IF NOT EXISTS verbatim_text_context TEXT;
ALTER TABLE processed_intent ADD COLUMN IF NOT EXISTS meeting_type VARCHAR(50);
ALTER TABLE processed_intent ADD COLUMN IF NOT EXISTS verification_score NUMERIC(5, 2);
ALTER TABLE processed_intent ADD COLUMN IF NOT EXISTS reviewer_status VARCHAR(50) DEFAULT 'unverified';


