# reviewer — GitHub Action based AI Security PR Reviewer.
#
# This package is the primary product surface for parity-zero (ADR-002).
# It runs inside a GitHub Actions workflow on pull request events and is
# responsible for:
#   - gathering changed files and PR metadata
#   - invoking the analysis engine (LLM-led review + narrow guardrails)
#   - producing a structured JSON ScanResult (the core contract)
#   - generating a developer-friendly markdown PR summary
#   - optionally posting results to the central ingestion API
