-- Preserve the original MigrateOS application in a private archive schema.
-- This runs after the TESSERA control-plane migration. It is intentionally
-- idempotent so a fresh TESSERA project is also safe to initialize.
create schema if not exists migrateos_legacy;

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'alembic_version', 'users', 'projects', 'repositories',
    'migration_jobs', 'migration_plans', 'executions', 'reports',
    'agent_logs', 'source_snapshots', 'approvals', 'artifacts', 'job_events'
  ] loop
    if to_regclass('public.' || table_name) is not null
       and to_regclass('migrateos_legacy.' || table_name) is null then
      execute format('alter table public.%I set schema migrateos_legacy', table_name);
    end if;
  end loop;
end $$;

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'alembic_version', 'users', 'projects', 'repositories',
    'migration_jobs', 'migration_plans', 'executions', 'reports',
    'agent_logs', 'source_snapshots', 'approvals', 'artifacts', 'job_events'
  ] loop
    if to_regclass('migrateos_legacy.' || table_name) is not null then
      execute format('alter table migrateos_legacy.%I enable row level security', table_name);
      if exists (select 1 from pg_roles where rolname = 'anon') then
        execute format('revoke all on table migrateos_legacy.%I from anon', table_name);
      end if;
      if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute format('revoke all on table migrateos_legacy.%I from authenticated', table_name);
      end if;
    end if;
  end loop;
end $$;
