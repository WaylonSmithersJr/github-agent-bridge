PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_key TEXT NOT NULL,
  repo TEXT,
  thread INTEGER,
  status TEXT NOT NULL CHECK(status IN ('pending','running','done','blocked','denied','waiting_approval')),
  action TEXT NOT NULL,
  decision TEXT NOT NULL,
  work_intent TEXT NOT NULL,
  subject TEXT NOT NULL,
  message_id TEXT NOT NULL UNIQUE,
  uid INTEGER,
  context_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0,
  coalesced_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  locked_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_work_status ON jobs(work_key, status);
CREATE TABLE IF NOT EXISTS coalesced_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  uid INTEGER,
  message_id TEXT NOT NULL UNIQUE,
  subject TEXT NOT NULL,
  context_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS worklog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  job_id INTEGER,
  work_key TEXT,
  phase TEXT NOT NULL,
  summary TEXT NOT NULL,
  detail TEXT
);
