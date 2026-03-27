# api — FastAPI ingestion stub for parity-zero.
#
# This package provides the central ingestion API (ADR-005).
# It receives structured scan results from reviewer runs, validates
# payloads against the findings schema, and will store them in Postgres
# in a later phase (ADR-006).
#
# Phase 1: thin stub with validation only.  No persistence layer yet.
