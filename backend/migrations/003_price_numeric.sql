alter table if exists products
  alter column price type numeric using price::numeric;
