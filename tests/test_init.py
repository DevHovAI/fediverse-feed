from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fediverse_feed.const import (
    CONF_MASTODON_INSTANCE,
    CONF_PIXELFED_INSTANCE,
    CONF_PIXELFED_TOKEN,
    DOMAIN,
)

LEMMY_URL = "https://lemmy.example/api/v3/post/list"
TAG_URL = "https://masto.example/api/v1/timelines/tag/memes"
PIXELFED = "https://pixelfed.example"


async def setup(hass: HomeAssistant, data: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=data or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def ask(hass_ws_client, **request):
    client = await hass_ws_client()
    await client.send_json_auto_id({"type": f"{DOMAIN}/posts", **request})
    return await client.receive_json()


async def test_config_flow_without_tokens(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_PIXELFED_INSTANCE: "pixelfed.social",
        CONF_MASTODON_INSTANCE: "mastodon.social",
    }


async def test_config_flow_rejects_bad_token(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{PIXELFED}/api/v1/accounts/verify_credentials", status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PIXELFED_INSTANCE: "pixelfed.example", CONF_PIXELFED_TOKEN: "wrong"}
    )
    assert result["errors"] == {CONF_PIXELFED_TOKEN: "invalid_token"}


async def test_lemmy_posts_and_cache(hass: HomeAssistant, hass_ws_client, aioclient_mock, lemmy_posts):
    aioclient_mock.get(LEMMY_URL, json=lemmy_posts)
    await setup(hass)
    request = {"source": "lemmy", "instance": "lemmy.example", "query": "memes"}
    request |= {"sort": "top", "period": "day"}
    msg = await ask(hass_ws_client, **request, count=5)
    assert msg["success"]
    assert [p["title"] for p in msg["result"]["posts"]] == ["Picture", "Link with preview"]
    url, params = aioclient_mock.mock_calls[0][1], aioclient_mock.mock_calls[0][1].query
    assert params["sort"] == "TopDay" and params["community_name"] == "memes", url

    # Same feed, other count: served from the cache
    msg = await ask(hass_ws_client, **request, count=1)
    assert len(msg["result"]["posts"]) == 1
    assert aioclient_mock.call_count == 1


async def test_mastodon_tag(hass: HomeAssistant, hass_ws_client, aioclient_mock, mastodon_tag):
    aioclient_mock.get(TAG_URL, json=mastodon_tag)
    await setup(hass)
    msg = await ask(hass_ws_client, source="mastodon", instance="masto.example", query="#memes",
                    sort="top", period="day", count=3)
    assert msg["success"]
    # Ranked by favourites + boosts within the last day; post 14 is two days old
    assert [p["id"] for p in msg["result"]["posts"]] == ["11", "10", "17"]


async def test_pixelfed_needs_token(hass: HomeAssistant, hass_ws_client, aioclient_mock):
    aioclient_mock.get(f"{PIXELFED}/api/v1/timelines/tag/cats", status=401)
    await setup(hass)
    msg = await ask(hass_ws_client, source="pixelfed", instance="pixelfed.example", query="cats")
    assert not msg["success"]
    assert msg["error"]["code"] == "auth_required"


async def test_pixelfed_sends_token(hass: HomeAssistant, hass_ws_client, aioclient_mock, mastodon_tag):
    aioclient_mock.get(f"{PIXELFED}/api/v1/timelines/tag/cats", json=mastodon_tag)
    await setup(hass, {CONF_PIXELFED_INSTANCE: "pixelfed.example", CONF_PIXELFED_TOKEN: "secret"})
    msg = await ask(hass_ws_client, source="pixelfed", instance="pixelfed.example", query="cats", sort="new")
    assert msg["success"]
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["Authorization"] == "Bearer secret"


async def test_not_set_up(hass: HomeAssistant, hass_ws_client):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    msg = await ask(hass_ws_client, source="lemmy")
    assert msg["error"]["code"] == "not_set_up"


async def test_card_is_served(hass: HomeAssistant, hass_client):
    await setup(hass)
    client = await hass_client()
    resp = await client.get("/fediverse_feed/fediverse-feed-card.js")
    assert resp.status == 200
    assert "fediverse-feed-card" in await resp.text()
