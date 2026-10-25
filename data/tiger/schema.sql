-- Tiger Data (TimescaleDB) schema for Tech Bazaar price history and the round curve.
-- Every statement is idempotent (IF NOT EXISTS or if_not_exists => true). Nothing here drops or truncates.
-- store.apply_schema() runs the statements one at a time on an autocommit connection (continuous
-- aggregates cannot be created inside a transaction). A statement preceded by the line "-- optional"
-- may fail (older server) without stopping the rest.

CREATE TABLE IF NOT EXISTS price_obs (
  ts TIMESTAMPTZ NOT NULL,
  sku TEXT NOT NULL,
  store TEXT NOT NULL,
  provider TEXT NOT NULL,
  price_cents INT NOT NULL,
  in_stock BOOL NOT NULL,
  origin TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT ''
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'sku', tsdb.orderby = 'ts DESC, store, provider, url');

CREATE TABLE IF NOT EXISTS bid_ticks (
  ts TIMESTAMPTZ NOT NULL,
  round_id TEXT NOT NULL,
  sku TEXT NOT NULL,
  seller_id TEXT NOT NULL,
  price_cents INT,
  event TEXT NOT NULL,
  origin TEXT
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'round_id', tsdb.orderby = 'ts DESC');

CREATE TABLE IF NOT EXISTS loss_reports (
  ts TIMESTAMPTZ NOT NULL,
  round_id TEXT,
  seller_id TEXT NOT NULL,
  sku TEXT,
  lost_by_cents INT,
  reason TEXT,
  origin TEXT
) WITH (tsdb.hypertable, tsdb.partition_column = 'ts', tsdb.segmentby = 'seller_id', tsdb.orderby = 'ts DESC');

-- Tables made before #260 have no origin column: add it (nullable, so it works on a columnstore table). A row with none reads as SIM.
ALTER TABLE bid_ticks ADD COLUMN IF NOT EXISTS origin TEXT;

ALTER TABLE loss_reports ADD COLUMN IF NOT EXISTS origin TEXT;

-- One observation per (time, sku, store, provider, listing url): a re-run of the loader inserts nothing new.
CREATE UNIQUE INDEX IF NOT EXISTS price_obs_uniq ON price_obs (ts, sku, store, provider, url);

-- price-discovery curve, real time (best sealed bid per round per 10 seconds)
CREATE MATERIALIZED VIEW IF NOT EXISTS bid_curve_10s WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
  SELECT round_id, sku, time_bucket('10 seconds', ts) AS bucket, min(price_cents) AS best_bid, count(*) AS bids
  FROM bid_ticks WHERE event = 'bid' GROUP BY round_id, sku, bucket WITH NO DATA;

-- market per hour: typical_cents is the median (percentile_cont); store.MARKET_1H_FALLBACK makes it the mean
-- when the server refuses percentile_cont inside a continuous aggregate.
CREATE MATERIALIZED VIEW IF NOT EXISTS market_1h WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
  SELECT sku, time_bucket('1 hour', ts) AS bucket, percentile_cont(0.5) WITHIN GROUP (ORDER BY price_cents) AS typical_cents,
         min(price_cents) AS min_cents, count(*) AS n
  FROM price_obs WHERE in_stock GROUP BY sku, bucket WITH NO DATA;

SELECT add_continuous_aggregate_policy('bid_curve_10s', start_offset => INTERVAL '1 day', end_offset => INTERVAL '10 seconds', schedule_interval => INTERVAL '1 minute', if_not_exists => true);

SELECT add_continuous_aggregate_policy('market_1h', start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '15 minutes', if_not_exists => true);

-- optional
SELECT add_columnstore_policy('price_obs', after => INTERVAL '7 days', if_not_exists => true);
