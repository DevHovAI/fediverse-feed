"""Fediverse Feed: pictures from Lemmy, Mastodon and Pixelfed in a dashboard card."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import PERIODS, SORTS, SOURCES, AuthRequired, FeedClient, FeedError, NotFound, Query, clean_instance
from .const import (
    CARD_URL,
    CONF_MASTODON_INSTANCE,
    CONF_MASTODON_TOKEN,
    CONF_PIXELFED_INSTANCE,
    CONF_PIXELFED_TOKEN,
    DOMAIN,
)
from .feed import FeedCache

type FeedConfigEntry = ConfigEntry[FeedCache]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the card, load it on every dashboard and offer the feed over the websocket."""
    integration = await async_get_integration(hass, DOMAIN)
    card = Path(__file__).parent / "frontend" / "fediverse-feed-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card), cache_headers=False)]
    )
    # The version in the URL makes browsers fetch the card again after an update.
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    websocket_api.async_register_command(hass, ws_posts)
    return True


def _tokens(entry: ConfigEntry) -> dict[str, str]:
    data = {**entry.data, **entry.options}
    tokens = {}
    for instance_key, token_key, source in (
        (CONF_PIXELFED_INSTANCE, CONF_PIXELFED_TOKEN, "pixelfed"),
        (CONF_MASTODON_INSTANCE, CONF_MASTODON_TOKEN, "mastodon"),
    ):
        if token := data.get(token_key):
            tokens[clean_instance(data.get(instance_key, ""), source)] = token
    return tokens


async def async_setup_entry(hass: HomeAssistant, entry: FeedConfigEntry) -> bool:
    entry.runtime_data = FeedCache(FeedClient(async_get_clientsession(hass), _tokens(entry)))
    # New tokens from the options take effect at once.
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: FeedConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FeedConfigEntry) -> bool:
    return True


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/posts",
        vol.Required("source"): vol.In(SOURCES),
        vol.Optional("instance", default=""): str,
        vol.Optional("query", default=""): str,
        vol.Optional("sort", default="top"): vol.In(SORTS),
        vol.Optional("period", default="day"): vol.In(PERIODS),
        vol.Optional("nsfw", default=False): bool,
        vol.Optional("images_only", default=True): bool,
        vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    }
)
@websocket_api.async_response
async def ws_posts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_set_up", "Fediverse Feed is not set up")
        return
    q = Query(
        source=msg["source"],
        instance=clean_instance(msg["instance"], msg["source"]),
        query=msg["query"],
        sort=msg["sort"],
        period=msg["period"],
        nsfw=msg["nsfw"],
        images_only=msg["images_only"],
        count=msg["count"],
    )
    try:
        posts = await entries[0].runtime_data.posts(q)
    except AuthRequired:
        connection.send_error(msg["id"], "auth_required", f"{q.instance} needs an access token")
        return
    except NotFound:
        connection.send_error(msg["id"], "not_found", f"{q.query} not found on {q.instance}")
        return
    except FeedError as err:
        connection.send_error(msg["id"], "cannot_connect", str(err))
        return
    connection.send_result(msg["id"], {"posts": [p.as_dict() for p in posts[: q.count]]})
