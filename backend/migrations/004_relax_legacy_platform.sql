do $$
begin
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
