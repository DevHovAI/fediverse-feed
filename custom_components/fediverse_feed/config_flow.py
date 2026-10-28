from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import DEFAULT_INSTANCES, AuthRequired, FeedClient, FeedError, clean_instance
from .const import (
    CONF_MASTODON_INSTANCE,
    CONF_MASTODON_TOKEN,
    CONF_PIXELFED_INSTANCE,
    CONF_PIXELFED_TOKEN,
    DOMAIN,
)

_FIELDS = (
    (CONF_PIXELFED_INSTANCE, CONF_PIXELFED_TOKEN, "pixelfed"),
    (CONF_MASTODON_INSTANCE, CONF_MASTODON_TOKEN, "mastodon"),
)


def _schema(values: dict[str, Any]) -> vol.Schema:
    password = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    fields: dict = {}
    for instance_key, token_key, source in _FIELDS:
        default = values.get(instance_key) or DEFAULT_INSTANCES[source]
        fields[vol.Optional(instance_key, default=default)] = str
        fields[vol.Optional(token_key, description={"suggested_value": values.get(token_key, "")})] = password
    return vol.Schema(fields)


async def _validate(hass, user_input: dict[str, Any]) -> dict[str, str]:
    """Check every token that was entered against its server."""
    errors: dict[str, str] = {}
    for instance_key, token_key, source in _FIELDS:
        token = (user_input.get(token_key) or "").strip()
        if not token:
            continue
        instance = clean_instance(user_input.get(instance_key, ""), source)
        client = FeedClient(async_get_clientsession(hass), {instance: token})
        try:
            await client.verify(instance)
        except AuthRequired:
            errors[token_key] = "invalid_token"
        except FeedError:
            errors[instance_key] = "cannot_connect"
    return errors


def _clean(user_input: dict[str, Any]) -> dict[str, str]:
    data = {}
    for instance_key, token_key, source in _FIELDS:
        data[instance_key] = clean_instance(user_input.get(instance_key, ""), source)
        if token := (user_input.get(token_key) or "").strip():
            data[token_key] = token
    return data


class FediverseFeedConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="Fediverse Feed", data=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FediverseFeedOptionsFlow()


class FediverseFeedOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=_clean(user_input))
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(user_input or current), errors=errors)
