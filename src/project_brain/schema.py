"""SQLite schema versions and forward-only migration definitions."""

SCHEMA_VERSION = 9

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

MIGRATION_2 = """
ALTER TABLE tasks ADD COLUMN attempt_phase TEXT NOT NULL DEFAULT 'implementation';
ALTER TABLE task_attempts ADD COLUMN phase TEXT NOT NULL DEFAULT 'implementation';
ALTER TABLE task_attempts ADD COLUMN base_sha TEXT;
ALTER TABLE task_attempts ADD COLUMN head_sha TEXT;
ALTER TABLE verification_results ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 0;

CREATE TABLE reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    head_sha TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('approved', 'needs_changes')),
    created_at TEXT NOT NULL
);

CREATE TABLE review_findings (
    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL REFERENCES reviews(review_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    head_sha TEXT NOT NULL,
    severity TEXT NOT NULL,
    file TEXT,
    evidence TEXT NOT NULL,
    requirement TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX reviews_task_head_idx ON reviews(task_id, head_sha);
CREATE INDEX review_findings_task_head_idx ON review_findings(task_id, head_sha);
CREATE INDEX verification_task_attempt_idx
    ON verification_results(task_id, attempt_number);
"""

MIGRATION_3 = """
ALTER TABLE agent_sessions ADD COLUMN child_pid INTEGER;
ALTER TABLE agent_sessions ADD COLUMN child_pgid INTEGER;
ALTER TABLE agent_sessions ADD COLUMN heartbeat_at TEXT;
UPDATE agent_sessions SET heartbeat_at = started_at WHERE heartbeat_at IS NULL;

CREATE TABLE verification_sets (
    verification_set_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    canonical_head_sha TEXT NOT NULL,
    source_attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(task_id, canonical_head_sha, source_attempt_number)
);

ALTER TABLE tasks ADD COLUMN verification_set_id INTEGER REFERENCES verification_sets(verification_set_id);
ALTER TABLE task_attempts ADD COLUMN verification_set_id INTEGER REFERENCES verification_sets(verification_set_id);
ALTER TABLE verification_results ADD COLUMN verification_set_id INTEGER REFERENCES verification_sets(verification_set_id);

INSERT INTO verification_sets(
    task_id, canonical_head_sha, source_attempt_number, status, created_at, completed_at
)
SELECT
    results.task_id,
    COALESCE(
        attempts.head_sha,
        CASE WHEN results.attempt_number = tasks.attempt_count
             THEN COALESCE(tasks.commit_sha, tasks.head_sha) END
    ),
    results.attempt_number,
    CASE WHEN SUM(CASE WHEN results.status = 'failed' THEN 1 ELSE 0 END) > 0
         THEN 'failed' ELSE 'completed' END,
    MIN(results.created_at),
    MAX(results.created_at)
FROM verification_results AS results
JOIN tasks ON tasks.task_id = results.task_id
LEFT JOIN task_attempts AS attempts
  ON attempts.task_id = results.task_id
 AND attempts.attempt_number = results.attempt_number
WHERE COALESCE(
    attempts.head_sha,
    CASE WHEN results.attempt_number = tasks.attempt_count
         THEN COALESCE(tasks.commit_sha, tasks.head_sha) END
) IS NOT NULL
GROUP BY
    results.task_id,
    COALESCE(
        attempts.head_sha,
        CASE WHEN results.attempt_number = tasks.attempt_count
             THEN COALESCE(tasks.commit_sha, tasks.head_sha) END
    ),
    results.attempt_number;

INSERT INTO verification_sets(
    task_id, canonical_head_sha, source_attempt_number, status, created_at, completed_at
)
SELECT
    tasks.task_id,
    tasks.commit_sha,
    tasks.attempt_count,
    'completed',
    tasks.updated_at,
    tasks.updated_at
FROM tasks
WHERE tasks.commit_sha IS NOT NULL
  AND tasks.attempt_phase IN ('publication', 'review')
  AND NOT EXISTS (
      SELECT 1 FROM verification_sets AS existing
      WHERE existing.task_id = tasks.task_id
        AND existing.canonical_head_sha = tasks.commit_sha
  );

UPDATE verification_results
SET verification_set_id = (
    SELECT sets.verification_set_id
    FROM verification_sets AS sets
    JOIN tasks ON tasks.task_id = verification_results.task_id
    LEFT JOIN task_attempts AS attempts
      ON attempts.task_id = verification_results.task_id
     AND attempts.attempt_number = verification_results.attempt_number
    WHERE sets.task_id = verification_results.task_id
      AND sets.source_attempt_number = verification_results.attempt_number
      AND sets.canonical_head_sha = COALESCE(
          attempts.head_sha,
          CASE WHEN verification_results.attempt_number = tasks.attempt_count
               THEN COALESCE(tasks.commit_sha, tasks.head_sha) END
      )
    ORDER BY sets.verification_set_id DESC
    LIMIT 1
);

UPDATE tasks
SET verification_set_id = (
    SELECT sets.verification_set_id
    FROM verification_sets AS sets
    WHERE sets.task_id = tasks.task_id
      AND sets.canonical_head_sha = COALESCE(tasks.commit_sha, tasks.head_sha)
    ORDER BY sets.verification_set_id DESC
    LIMIT 1
);

UPDATE task_attempts
SET verification_set_id = (
    SELECT sets.verification_set_id
    FROM verification_sets AS sets
    WHERE sets.task_id = task_attempts.task_id
      AND sets.source_attempt_number = task_attempts.attempt_number
    ORDER BY sets.verification_set_id DESC
    LIMIT 1
);

CREATE INDEX verification_sets_task_head_idx
    ON verification_sets(task_id, canonical_head_sha, verification_set_id);
CREATE INDEX verification_results_set_idx
    ON verification_results(verification_set_id, verification_id);

CREATE TABLE forensic_archives (
    archive_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    worktree_id INTEGER NOT NULL REFERENCES worktrees(worktree_id),
    artifact_path TEXT NOT NULL UNIQUE,
    manifest_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(task_id, worktree_id)
);
"""

MIGRATION_4 = """
ALTER TABLE agent_sessions ADD COLUMN child_identity_json TEXT;
"""

MIGRATION_5 = """
ALTER TABLE projects ADD COLUMN config_revision INTEGER;
ALTER TABLE projects ADD COLUMN config_sha256 TEXT;
ALTER TABLE projects ADD COLUMN config_updated_at TEXT;
ALTER TABLE projects ADD COLUMN config_source TEXT;
ALTER TABLE tasks ADD COLUMN project_config_revision INTEGER;
ALTER TABLE tasks ADD COLUMN project_config_sha256 TEXT;
ALTER TABLE tasks ADD COLUMN execution_profile_json TEXT;
"""

MIGRATION_6 = """
ALTER TABLE projects ADD COLUMN accepting_tasks INTEGER NOT NULL DEFAULT 1;
ALTER TABLE projects ADD COLUMN registered INTEGER NOT NULL DEFAULT 1;
"""

MIGRATION_7 = """
CREATE TABLE installation_identity (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    installation_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE external_acceptance_runs (
    run_id TEXT PRIMARY KEY,
    challenge_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN (
        'not_started', 'challenge_ready', 'waiting_for_chatgpt', 'passed',
        'failed', 'expired', 'superseded'
    )),
    core_version TEXT NOT NULL,
    app_version TEXT NOT NULL,
    installation_id TEXT NOT NULL REFERENCES installation_identity(installation_id),
    tunnel_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    waiting_at TEXT,
    verified_at TEXT,
    failure_code TEXT,
    ingress TEXT,
    probe_count INTEGER NOT NULL DEFAULT 0 CHECK(probe_count >= 0)
);

CREATE INDEX external_acceptance_status_created_idx
    ON external_acceptance_runs(status, created_at);
CREATE INDEX external_acceptance_verified_idx
    ON external_acceptance_runs(verified_at);

CREATE TABLE external_acceptance_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES external_acceptance_runs(run_id),
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX external_acceptance_events_run_idx
    ON external_acceptance_events(run_id, event_id);
"""

MIGRATION_8 = """
ALTER TABLE external_acceptance_events RENAME TO external_acceptance_events_v7;
ALTER TABLE external_acceptance_runs RENAME TO external_acceptance_runs_v7;

DROP INDEX external_acceptance_status_created_idx;
DROP INDEX external_acceptance_verified_idx;
DROP INDEX external_acceptance_events_run_idx;

CREATE TABLE external_acceptance_runs (
    run_id TEXT PRIMARY KEY,
    challenge_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN (
        'not_started', 'challenge_ready', 'waiting_for_chatgpt',
        'mcp_transport_probe_passed', 'failed', 'expired', 'superseded'
    )),
    core_version TEXT NOT NULL,
    app_version TEXT NOT NULL,
    acceptance_contract_version INTEGER NOT NULL,
    installation_id TEXT NOT NULL REFERENCES installation_identity(installation_id),
    tunnel_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    waiting_at TEXT,
    verified_at TEXT,
    failure_code TEXT,
    ingress TEXT,
    probe_count INTEGER NOT NULL DEFAULT 0 CHECK(probe_count >= 0)
);

INSERT INTO external_acceptance_runs(
    run_id, challenge_sha256, status, core_version, app_version,
    acceptance_contract_version, installation_id, tunnel_fingerprint,
    created_at, expires_at, waiting_at, verified_at, failure_code, ingress,
    probe_count
)
SELECT
    run_id,
    challenge_sha256,
    CASE WHEN status = 'passed' THEN 'mcp_transport_probe_passed' ELSE status END,
    core_version,
    app_version,
    1,
    installation_id,
    tunnel_fingerprint,
    created_at,
    expires_at,
    waiting_at,
    verified_at,
    failure_code,
    CASE
        WHEN status = 'passed' THEN 'local_or_tunneled_mcp_unattributed'
        ELSE ingress
    END,
    probe_count
FROM external_acceptance_runs_v7;

CREATE TABLE external_acceptance_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES external_acceptance_runs(run_id),
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO external_acceptance_events(
    event_id, run_id, event_type, from_status, to_status, payload_json, created_at
)
SELECT
    event_id,
    run_id,
    CASE
        WHEN event_type = 'acceptance_probe_passed'
            THEN 'mcp_transport_probe_recorded'
        ELSE event_type
    END,
    CASE WHEN from_status = 'passed' THEN 'mcp_transport_probe_passed' ELSE from_status END,
    CASE WHEN to_status = 'passed' THEN 'mcp_transport_probe_passed' ELSE to_status END,
    CASE
        WHEN event_type = 'acceptance_probe_passed'
            THEN '{"external_chatgpt_verified":false,"ingress":"local_or_tunneled_mcp_unattributed","migrated_from_v7":true}'
        ELSE payload_json
    END,
    created_at
FROM external_acceptance_events_v7;

DROP TABLE external_acceptance_events_v7;
DROP TABLE external_acceptance_runs_v7;

CREATE INDEX external_acceptance_status_created_idx
    ON external_acceptance_runs(status, created_at);
CREATE INDEX external_acceptance_verified_idx
    ON external_acceptance_runs(verified_at);
CREATE INDEX external_acceptance_events_run_idx
    ON external_acceptance_events(run_id, event_id);
"""

MIGRATION_9 = """
ALTER TABLE tasks ADD COLUMN local_task_type TEXT;
ALTER TABLE tasks ADD COLUMN delivery_json TEXT;
ALTER TABLE tasks ADD COLUMN result_json TEXT;

CREATE TABLE local_task_plans (
    plan_token TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK(schema_version = 1),
    request_sha256 TEXT NOT NULL,
    request_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    project_config_revision INTEGER NOT NULL,
    project_config_sha256 TEXT NOT NULL,
    base_sha TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    task_id TEXT UNIQUE REFERENCES tasks(task_id)
);

CREATE INDEX local_task_plans_expiry_idx
    ON local_task_plans(expires_at, consumed_at);
CREATE INDEX local_task_plans_project_idx
    ON local_task_plans(project_id, created_at);
"""

MIGRATIONS = {
    1: MIGRATION_1,
    2: MIGRATION_2,
    3: MIGRATION_3,
    4: MIGRATION_4,
    5: MIGRATION_5,
    6: MIGRATION_6,
    7: MIGRATION_7,
    8: MIGRATION_8,
    9: MIGRATION_9,
}
