-- TESSERA control-plane schema for Supabase PostgreSQL.
-- The API uses DATABASE_URL server-side; browser clients never access these tables.
create extension if not exists vector;

create table if not exists users (
  username text primary key, password_hash text not null, role text not null,
  active boolean not null default true, created_at timestamptz not null default now()
);
create table if not exists auth_sessions (
  jti text primary key, username text not null references users(username),
  issued_at bigint not null, expires_at bigint not null, revoked_at bigint
);
create index if not exists idx_auth_sessions_user on auth_sessions(username, expires_at);
create table if not exists runs (
  run_id text primary key, status text not null, created_at timestamptz not null,
  replay_of text, payload jsonb not null
);
create table if not exists ledger_entries (
  sequence bigint generated always as identity primary key, entry_id text not null unique,
  run_id text not null, entry_type text not null, actor text not null,
  created_at timestamptz not null, payload jsonb not null, payload_hash text not null,
  previous_hash text not null, entry_hash text not null unique
);
create index if not exists idx_ledger_run on ledger_entries(run_id, sequence);
create table if not exists system_state (key text primary key, value jsonb not null);
create table if not exists idempotency_keys (
  scope text not null, key text not null, resource_id text not null,
  created_at timestamptz not null default now(), primary key(scope, key)
);
create table if not exists model_calls (
  call_id bigint generated always as identity primary key, created_at timestamptz not null default now(),
  provider text not null, model text not null, agent text not null, input_hash text not null,
  latency_ms double precision not null, validation_status text not null,
  run_id text not null default 'UNSCOPED', prompt_version text not null default 'agent-v1',
  output_hash text not null default '', token_usage jsonb not null default '{}'::jsonb,
  retry_count integer not null default 0
);
create table if not exists market_observations (
  observation_id text primary key, symbol text not null, observed_at timestamptz not null,
  payload jsonb not null
);
create index if not exists idx_observations_symbol_time on market_observations(symbol, observed_at desc);
create table if not exists market_edges (
  edge_id text primary key, source text not null, target text not null,
  relation text not null, payload jsonb not null
);
create index if not exists idx_edges_source_target on market_edges(source, target);
create table if not exists strategy_versions (
  strategy_id text not null, version integer not null, created_at timestamptz not null,
  payload jsonb not null, primary key(strategy_id, version)
);
create table if not exists jobs (
  job_id text primary key, job_type text not null, status text not null,
  payload jsonb not null, result jsonb, error text, attempts integer not null default 0,
  available_at timestamptz not null, lease_until timestamptz, worker_id text,
  created_at timestamptz not null, updated_at timestamptz not null
);
create index if not exists idx_jobs_claim on jobs(status, available_at, lease_until, created_at);
create table if not exists replays (
  replay_id text primary key, original_run_id text not null, replay_run_id text not null,
  created_at timestamptz not null, artifact_key text not null, payload jsonb not null
);
create table if not exists asset_embeddings (
  embedding_id text primary key, asset text not null, content_hash text not null,
  embedding vector(1536) not null, metadata jsonb not null, created_at timestamptz not null
);

-- TESSERA connects with the server-side database role. Public Supabase API roles
-- must not reach these control-plane tables; RLS remains defense in depth.
do $$ declare table_name text; begin
  foreach table_name in array array['users','auth_sessions','runs','ledger_entries','system_state',
    'idempotency_keys','model_calls','market_observations','market_edges','strategy_versions',
    'jobs','replays','asset_embeddings'] loop
    execute format('alter table %I enable row level security', table_name);
    execute format('revoke all on table %I from anon, authenticated', table_name);
  end loop;
end $$;
