-- Runs once on first Postgres start (docker-entrypoint-initdb.d).

CREATE EXTENSION IF NOT EXISTS vector;

-- Separate database for the target ("victim") checkout service so the
-- investigator's own tables never mix with the thing under investigation.
CREATE DATABASE checkout;

-- Read-only role used by the query_database tool. Never grant writes.
CREATE ROLE investigator_ro LOGIN PASSWORD 'investigator_ro';
GRANT CONNECT ON DATABASE checkout TO investigator_ro;
ALTER ROLE investigator_ro SET statement_timeout = '5s';
ALTER ROLE investigator_ro SET default_transaction_read_only = on;

\connect checkout
GRANT USAGE ON SCHEMA public TO investigator_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO investigator_ro;
