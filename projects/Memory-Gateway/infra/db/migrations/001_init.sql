CREATE TABLE api_keys (
  key_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL,
  user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, agent_type TEXT NOT NULL,
  allowed_workspace_ids JSONB NOT NULL DEFAULT '[]',
  model_allowlist JSONB NOT NULL DEFAULT '[]', scopes JSONB NOT NULL DEFAULT '[]',
  default_model TEXT NOT NULL, quota_tokens BIGINT NOT NULL DEFAULT 1000000,
  rate_qps INT NOT NULL DEFAULT 10, allow_silent_fallback BOOLEAN NOT NULL DEFAULT FALSE,
  label_version INT NOT NULL DEFAULT 1,
  expires_at BIGINT, is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
  created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL);
CREATE UNIQUE INDEX ux_api_keys_hash ON api_keys(key_hash);
CREATE INDEX ix_api_keys_ws ON api_keys(workspace_id);

CREATE TABLE memories (
  id BIGSERIAL PRIMARY KEY,
  memory_id VARCHAR(64) UNIQUE NOT NULL,
  user_id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
  project_id VARCHAR(64), session_id VARCHAR(64), agent_id VARCHAR(64),
  content TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL,
  entity_key VARCHAR(128), memory_class VARCHAR(32) NOT NULL DEFAULT 'episode',
  tier VARCHAR(16) NOT NULL DEFAULT 'L3_SEMANTIC',
  confidence REAL NOT NULL DEFAULT 0.7, importance REAL NOT NULL DEFAULT 0.5,
  trust VARCHAR(16) NOT NULL DEFAULT 'trusted',
  origin_type VARCHAR(32) NOT NULL DEFAULT 'conversation',
  valid_from BIGINT NOT NULL, valid_until BIGINT,
  supersedes VARCHAR(64), superseded_by VARCHAR(64),
  access_count INT NOT NULL DEFAULT 0,
  last_accessed_at BIGINT, embedding_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  retry_count INT NOT NULL DEFAULT 0,
  is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL);
CREATE INDEX ix_mem_scope ON memories(workspace_id, user_id, memory_class, valid_until)
  WHERE is_deleted = FALSE;
CREATE INDEX ix_mem_entity ON memories(workspace_id, user_id, entity_key)
  WHERE superseded_by IS NULL AND is_deleted = FALSE AND entity_key IS NOT NULL;
CREATE INDEX ix_mem_pending ON memories(embedding_status, retry_count) WHERE is_deleted = FALSE;

CREATE TABLE sessions (
  session_id VARCHAR(64) PRIMARY KEY,
  user_id VARCHAR(64) NOT NULL, workspace_id VARCHAR(64) NOT NULL,
  project_id VARCHAR(64), agent_type VARCHAR(32),
  resident_model VARCHAR(64), pinned_until BIGINT, pin_reason VARCHAR(32),
  created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL);

CREATE TABLE messages (
  id BIGSERIAL PRIMARY KEY, conversation_id VARCHAR(64) NOT NULL,
  conversation_seq BIGINT NOT NULL, turn_no INT, role VARCHAR(16) NOT NULL,
  content TEXT, token_count INT, model_used VARCHAR(64), trace_id VARCHAR(64),
  created_at BIGINT NOT NULL);
CREATE UNIQUE INDEX ux_msg_seq ON messages(conversation_id, conversation_seq);

CREATE TABLE memory_index_outbox (
  id BIGSERIAL PRIMARY KEY, memory_id VARCHAR(64) NOT NULL,
  op VARCHAR(16) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0, next_retry_at BIGINT NOT NULL DEFAULT 0,
  last_error TEXT, created_at BIGINT NOT NULL);
CREATE INDEX ix_outbox_ready ON memory_index_outbox(status, next_retry_at);

CREATE TABLE writeback_queue (
  id BIGSERIAL PRIMARY KEY, idem_key VARCHAR(128) UNIQUE NOT NULL,
  user_id TEXT NOT NULL, workspace_id TEXT NOT NULL, tier VARCHAR(8) NOT NULL,
  payload JSONB NOT NULL, keep_always BOOLEAN NOT NULL DEFAULT FALSE,
  attempts INT NOT NULL DEFAULT 0, status VARCHAR(16) NOT NULL DEFAULT 'pending',
  created_at BIGINT NOT NULL, claimed_at BIGINT, last_error TEXT);
CREATE INDEX ix_wb_claim ON writeback_queue(status, created_at, id);
