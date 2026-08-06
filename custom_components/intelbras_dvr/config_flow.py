"""Config flow do intelbras_dvr."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CHANNELS,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_RTSP_SUBTYPE,
    CONF_SCAN_INTERVAL,
    CONF_TRACK_BY_MAC,
    DEFAULT_CHANNELS,
    DEFAULT_HTTP_PORT,
    DEFAULT_RTSP_PORT,
    DEFAULT_RTSP_SUBTYPE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USERNAME,
    DOMAIN,
)
from .dvr import IntelbrasClient, discover_mac


def _user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): cv.string,
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, DEFAULT_USERNAME)): cv.string,
            vol.Required(CONF_PASSWORD, default=d.get(CONF_PASSWORD, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_CHANNELS, default=d.get(CONF_CHANNELS, DEFAULT_CHANNELS)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=32)
            ),
            vol.Optional(CONF_RTSP_PORT, default=d.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional(
                CONF_RTSP_SUBTYPE, default=d.get(CONF_RTSP_SUBTYPE, DEFAULT_RTSP_SUBTYPE)
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1)),
            vol.Optional(
                CONF_HTTP_PORT, default=d.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional(CONF_TRACK_BY_MAC, default=d.get(CONF_TRACK_BY_MAC, True)): cv.boolean,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Fluxo de configuração inicial."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = IntelbrasClient(
                user_input[CONF_HOST],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                http_port=user_input.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT),
            )
            result = await client.probe()
            if not result.ok:
                errors["base"] = "auth_failed"
            else:
                mac = await self.hass.async_add_executor_job(
                    discover_mac, user_input[CONF_HOST]
                )
                data = {**user_input}
                if mac:
                    data["mac"] = mac
                await self.async_set_unique_id(
                    mac or f"{user_input[CONF_HOST]}-{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"DVR {user_input[CONF_HOST]}",
                    data=data,
                )
        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input), errors=errors
        )

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry) -> "OptionsFlow":
        return OptionsFlow(entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Permite re-tunar canais, track_by_mac, scan_interval sem recriar."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        merged = {**self.entry.data, **self.entry.options}
        schema = vol.Schema(
            {
                vol.Optional(CONF_CHANNELS, default=merged.get(CONF_CHANNELS, DEFAULT_CHANNELS)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=32)
                ),
                vol.Optional(CONF_RTSP_PORT, default=merged.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Optional(
                    CONF_RTSP_SUBTYPE,
                    default=merged.get(CONF_RTSP_SUBTYPE, DEFAULT_RTSP_SUBTYPE),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1)),
                vol.Optional(
                    CONF_HTTP_PORT, default=merged.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_TRACK_BY_MAC, default=merged.get(CONF_TRACK_BY_MAC, True)
                ): cv.boolean,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
