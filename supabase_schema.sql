create table if not exists post_approvals (
  post_key text primary key,
  slot text not null,
  scheduled_for date not null,
  status text not null check (status in ('pending','approved','rejected')),
  content_path text not null,
  content text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  approved_at timestamptz,
  rejected_at timestamptz,
  posted_at timestamptz,
  posted_tweet_id text
);

create table if not exists telegram_state (
  id int primary key default 1 check (id = 1),
  last_update_id bigint not null default 0,
  updated_at timestamptz not null default now()
);

insert into telegram_state (id, last_update_id)
values (1, 0)
on conflict (id) do nothing;
