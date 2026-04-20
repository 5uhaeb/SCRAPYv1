alter table if exists products
  add column if not exists source_platform text,
  add column if not exists product_url text,
  add column if not exists title text,
  add column if not exists price numeric,
  add column if not exists currency text default 'INR',
  add column if not exists image_url text,
  add column if not exists keyword text,
  add column if not exists scraped_at timestamptz default now(),
  add column if not exists raw jsonb,
  add column if not exists product_hash text;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_name = 'products' and column_name = 'platform'
  ) then
    update products
    set source_platform = coalesce(source_platform, platform)
    where source_platform is null;
  end if;

  if exists (
    select 1 from information_schema.columns
    where table_name = 'products' and column_name = 'platform'
  ) then
    update products
    set platform = coalesce(platform, source_platform)
    where platform is null;

    alter table products
      alter column platform drop not null;
  end if;
end $$;

update products
set currency = coalesce(currency, 'INR'),
    scraped_at = coalesce(scraped_at, now()),
    product_hash = coalesce(
      product_hash,
      md5(lower(regexp_replace(coalesce(title, ''), '[^a-zA-Z0-9]+', ' ', 'g')) || coalesce(source_platform, ''))
    );

alter table if exists products
  alter column price type numeric using price::numeric;

with ranked as (
  select
    ctid,
    row_number() over (
      partition by source_platform, product_url
      order by scraped_at desc nulls last
    ) as rn
  from products
  where source_platform is not null
    and product_url is not null
)
delete from products p
using ranked r
where p.ctid = r.ctid
  and r.rn > 1;

create unique index if not exists products_source_platform_product_url_key
  on products (source_platform, product_url)
  where source_platform is not null and product_url is not null;

create index if not exists products_keyword_platform_scraped_idx
  on products (keyword, source_platform, scraped_at desc);

create table if not exists price_history (
  id bigserial primary key,
  product_hash text not null,
  price numeric,
  currency text default 'INR',
  scraped_at timestamptz default now(),
  source_platform text
);

create index if not exists price_history_product_hash_scraped_idx
  on price_history (product_hash, scraped_at);

create table if not exists watchlist (
  id bigserial primary key,
  product_hash text not null,
  chat_id text,
  target_price numeric not null,
  created_at timestamptz default now()
);

create index if not exists watchlist_product_hash_idx
  on watchlist (product_hash);
