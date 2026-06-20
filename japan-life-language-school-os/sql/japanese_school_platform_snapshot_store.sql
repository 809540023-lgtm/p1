create table if not exists school_platform_snapshots (
    snapshot_key text primary key,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
