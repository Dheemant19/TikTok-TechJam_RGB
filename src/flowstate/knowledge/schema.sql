PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  authors_json TEXT NOT NULL,
  venue TEXT,
  year INTEGER,
  abstract TEXT,
  paper_url TEXT,
  license TEXT,
  retracted INTEGER NOT NULL DEFAULT 0,
  trust_tier TEXT NOT NULL,
  content_completeness TEXT NOT NULL,
  priority_areas_json TEXT NOT NULL,
  relevance_notes TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  sanitizer_flags_json TEXT NOT NULL,
  quarantined INTEGER NOT NULL DEFAULT 0,
  raw_content_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE,
  current_version_id INTEGER,
  retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_versions (
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL REFERENCES papers(paper_id),
  content_hash TEXT NOT NULL,
  record_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(paper_id, content_hash)
);

CREATE TABLE IF NOT EXISTS paper_identifiers (
  paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY(kind, value),
  UNIQUE(paper_id, kind)
);

CREATE TABLE IF NOT EXISTS code_implementations (
  code_id INTEGER PRIMARY KEY AUTOINCREMENT,
  repository_url TEXT NOT NULL,
  pinned_commit TEXT,
  license TEXT,
  stars INTEGER,
  topics_json TEXT NOT NULL DEFAULT '[]',
  paper_id TEXT REFERENCES papers(paper_id) ON DELETE CASCADE,
  source_url TEXT,
  content_hash TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  UNIQUE(repository_url, paper_id)
);

CREATE TABLE IF NOT EXISTS citation_edges (
  source_paper_id TEXT NOT NULL,
  target_paper_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  provider TEXT NOT NULL,
  PRIMARY KEY(source_paper_id, target_paper_id, relation, provider)
);

CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(
  paper_id UNINDEXED,
  title,
  abstract,
  keywords,
  priority_areas,
  relevance_notes,
  tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS paper_vectors (
  paper_id TEXT PRIMARY KEY REFERENCES papers(paper_id) ON DELETE CASCADE,
  embedding_model_id TEXT NOT NULL,
  embedding_revision TEXT NOT NULL,
  dimension INTEGER NOT NULL,
  vector BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS query_cache (
  cache_key TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  request_json TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  hit_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ingestion_queue (
  queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_key TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  requested_query TEXT,
  payload_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','processing','succeeded','rejected','failed')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  lease_timestamp TEXT,
  last_error TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_events (
  event_id TEXT PRIMARY KEY,
  queue_id INTEGER,
  work_key TEXT NOT NULL,
  source TEXT NOT NULL,
  outcome TEXT NOT NULL,
  paper_id TEXT,
  content_hash TEXT,
  detail_json TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_usage (
  usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  experiment_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  request_id TEXT NOT NULL,
  outbound_requests INTEGER NOT NULL DEFAULT 0,
  documents_returned INTEGER NOT NULL DEFAULT 0,
  response_characters INTEGER NOT NULL DEFAULT 0,
  bytes_received INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  retry_count INTEGER NOT NULL DEFAULT 0,
  occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_session ON provider_usage(session_id, provider);
CREATE INDEX IF NOT EXISTS idx_usage_experiment ON provider_usage(session_id, experiment_id, provider);
CREATE INDEX IF NOT EXISTS idx_queue_state ON ingestion_queue(state, lease_timestamp);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
