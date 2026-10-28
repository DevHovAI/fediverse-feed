import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def lemmy_posts() -> dict:
    return json.loads((FIXTURES / "lemmy_posts.json").read_text())


@pytest.fixture
def mastodon_tag() -> list:
    # created_at is stored as "AGE:<hours>" so the ranking by age does not rot over time.
    statuses = json.loads((FIXTURES / "mastodon_tag.json").read_text())
    now = datetime.now(UTC)
    for s in statuses:
        hours = int(s["created_at"].split(":")[1])
        s["created_at"] = (now - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return statuses
