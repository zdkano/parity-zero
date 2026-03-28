# Release & Packaging

## Current State

parity-zero is functional as a GitHub Action that can be referenced by repository path:

```yaml
# From the same repository
uses: ./

# From another repository
uses: zdkano/parity-zero@main
```

The action is defined in `action.yml` as a composite action that:
1. Sets up Python 3.12
2. Installs dependencies from `requirements.txt`
3. Runs `python -m reviewer.action`

## GitHub Marketplace Direction

parity-zero is being built toward GitHub Marketplace distribution. This is an intended future direction, not a current capability.

### What is needed for Marketplace packaging

- **Versioned releases** — tagged releases (e.g. `v1.0.0`) so consumers can pin to stable versions
- **Action branding** — `action.yml` needs `branding` metadata (icon, color) for Marketplace listing
- **Documentation polish** — clear Marketplace listing description and usage instructions
- **Testing across repository types** — validation beyond the current curated scenario corpus

### What is already in place

- `action.yml` composite action definition
- Python 3.12 setup
- Dependency installation
- PR base fetch for git diff
- Reviewer execution via `python -m reviewer.action`
- **Real file content loading** from workspace checkout
- **Changed file discovery** via git diff with API fallback
- Structured JSON output (ScanResult)
- Markdown summary generation
- **GitHub job summary** output (GITHUB_STEP_SUMMARY)
- **PR comment posting** with update-not-duplicate behavior
- Provider configuration via environment variables
- Safe fallback when providers are not configured

## Versioning

No tagged releases exist yet. The action is currently referenced by branch (`@main`).

When ready for broader distribution:
1. Tag a release: `git tag v1.0.0 && git push origin v1.0.0`
2. Create a GitHub Release from the tag
3. Update documentation to reference the tag
4. Submit to GitHub Marketplace (if appropriate)

## What This Is Not

parity-zero does not claim to be Marketplace-ready today. The reviewer pipeline is functional and the action works, but the packaging and integration polish expected for a production Marketplace listing is still in progress.

Avoid:
- Publishing to Marketplace before broader testing across different repository types
- Claiming production-readiness without versioned releases
- Skipping versioned releases — consumers need stable reference points
