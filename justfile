# Fediverse Feed — local checks. The venv needs Python 3.14 (Home Assistant's minimum):
#   uv venv -p 3.14 .venv && uv pip install -p .venv -r requirements-dev.txt

set shell := ["bash", "-euo", "pipefail", "-c"]

# Everything the CI runs (except hassfest/HACS). Do this before every push.
check:
    .venv/bin/ruff check .
    .venv/bin/pytest -q
    node --check custom_components/fediverse_feed/frontend/fediverse-feed-card.js
    python3 -c "import json; [json.load(open(f)) for f in ['hacs.json', 'custom_components/fediverse_feed/manifest.json']]"
    bash ~/.claude/skills/repo-flow/scripts/privacy-scan.sh
