"""Setup do intelbras_dvr + serviço apply_credentials."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .apply_helper import apply_credentials
from .const import (
    CONF_HTTP_PORT,
    DATA_COORDINATOR,
    DEFAULT_HTTP_PORT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import IntelbrasCoordinator
from .dvr import IntelbrasClient

_LOGGER = logging.getLogger(__name__)

SERVICE_APPLY = "apply_credentials"

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

APPLY_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Registra o serviço uma única vez."""
    hass.data.setdefault(DOMAIN, {})

    async def _apply(call: ServiceCall) -> None:
        entries = list(hass.config_entries.async_entries(DOMAIN))
        target_id = call.data.get("entry_id")
        entry: ConfigEntry | None = None
        if target_id:
            entry = next((e for e in entries if e.entry_id == target_id), None)
            if entry is None:
                raise HomeAssistantError(f"entry_id {target_id} não encontrada.")
        elif len(entries) == 1:
            entry = entries[0]
        elif len(entries) > 1:
            raise HomeAssistantError(
                "Múltiplas instalações: especifique entry_id na chamada."
            )

        host = call.data[CONF_HOST]
        user = call.data[CONF_USERNAME]
        pwd = call.data[CONF_PASSWORD]

        outcome = await apply_credentials(hass, host, user, pwd, entry)
        if not outcome.ok:
            persistent_notification.async_create(
                hass,
                outcome.message,
                title="DVR Intelbras",
                notification_id="intelbras_dvr_apply",
            )
            raise HomeAssistantError(f"Login falhou: {outcome.message}")

        persistent_notification.async_create(
            hass,
            outcome.message
            + (" — câmeras recarregadas" if outcome.generic_updated else ""),
            title="DVR Intelbras",
            notification_id="intelbras_dvr_apply",
        )

        if entry is not None:
            await hass.config_entries.async_reload(entry.entry_id)


    hass.services.async_register(DOMAIN, SERVICE_APPLY, _apply, schema=APPLY_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inicializa uma instalação do DVR."""
    client = IntelbrasClient(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        http_port=entry.options.get(
            CONF_HTTP_PORT, entry.data.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT)
        ),
    )
    coordinator = IntelbrasCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN].setdefault(entry.entry_id, {})
    hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR] = coordinator
    hass.data[DOMAIN][entry.entry_id]["client"] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
