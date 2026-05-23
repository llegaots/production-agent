-- Phase 1: enable PostGIS for geo fields in later phases.
-- Safe to re-run: IF NOT EXISTS is supported on extensions in Postgres 9.1+.
CREATE EXTENSION IF NOT EXISTS postgis;
