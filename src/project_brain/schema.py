"""SQLite schema versions and forward-only migration definitions."""

SCHEMA_VERSION = 1

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    repo_path TEXT NOT NULL,
    remote_url TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    worktree_root TEXT NOT NULL,
    codex_command_json TEXT NOT NULL,
    verification_commands_json TEXT NOT NULL,
    allowed_commands_json TEXT NOT NULL,
    auto_push INTEGER NOT NULL DEFAULT 1,
    auto_pr INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    dedupe_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    source_type TEXT NOT NULL,
    source_message_id TEXT,
    goal TEXT NOT NULL,
    acceptance_criteria_json TEXT NOT NULL,
    task_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    branch TEXT,
    base_sha TEXT,
    head_sha TEXT,
    worktree_path TEXT,
    agent_session_id TEXT,
    commit_sha TEXT,
    pr_url TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    supersedes TEXT REFERENCES tasks(task_id),
    UNIQUE(project_id, dedupe_key, revision)
);

CREATE INDEX IF NOT EXISTS tasks_status_created_idx
    ON tasks(status, created_at);
CREATE INDEX IF NOT EXISTS tasks_dedupe_idx
    ON tasks(project_id, dedupe_key, revision);

CREATE TABLE IF NOT EXISTS task_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_category TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(task_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS worktrees (
    worktree_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(task_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    path TEXT NOT NULL UNIQUE,
    branch TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    status TEXT NOT NULL,
    owner_pid INTEGER,
    heartbeat_at TEXT,
    created_at TEXT NOT NULL,
    cleaned_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    adapter TEXT NOT NULL,
    command_json TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_code INTEGER,
    output_summary TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS verification_results (
    verification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    criterion_id TEXT NOT NULL,
    criterion_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('passed', 'failed', 'not_verified')),
    evidence_type TEXT NOT NULL,
    evidence_summary TEXT NOT NULL,
    command_json TEXT,
    exit_code INTEGER,
    artifact_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT REFERENCES tasks(task_id),
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MIGRATIONS = {1: MIGRATION_1}
