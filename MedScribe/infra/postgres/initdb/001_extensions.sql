-- Enables gen_random_uuid() for UUID primary keys across the schema
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Enables case-insensitive text type, useful for email/username lookups
CREATE EXTENSION IF NOT EXISTS citext;
