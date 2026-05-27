"""Setup do intelbras_dvr + serviço apply_credentials."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    DATA_COORDINATOR,
    DATA_MAC,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import IntelbrasCoordinator
from .dvr import IntelbrasClient, discover_mac

_LOGGER = logging.getLogger(__name__)

SERVICE_APPLY = "apply_credentials"

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
        if not entries:
            raise HomeAssistantError("Nenhuma instalação Intelbras DVR encontrada.")
        target_id = call.data.get("entry_id")
        if target_id:
            entry = next((e for e in entries if e.entry_id == target_id), None)
            if entry is None:
                raise HomeAssistantError(f"entry_id {target_id} não encontrada.")
        elif len(entries) == 1:
            entry = entries[0]
        else:
            raise HomeAssistantError(
                "Múltiplas instalações: especifique entry_id na chamada."
            )

        host = call.data[CONF_HOST]
        user = call.data[CONF_USERNAME]
        pwd = call.data[CONF_PASSWORD]

        client = IntelbrasClient(host, user, pwd)
        result = await client.probe()
        coord: IntelbrasCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
        if not result.ok:
            coord.set_last_result(f"FAIL: {result.error} (HTTP={result.http_code})")
            raise HomeAssistantError(f"Login falhou: {result.error}")

        mac = await hass.async_add_executor_job(discover_mac, host)
        new_data = {
            **entry.data,
            CONF_HOST: host,
            CONF_USERNAME: user,
            CONF_PASSWORD: pwd,
        }
        if mac:
            new_data[DATA_MAC] = mac
        hass.config_entries.async_update_entry(entry, data=new_data)
        coord.set_last_result(
            f"OK: {host} validado"
            + (f" (MAC {mac})" if mac else " (MAC desconhecido)")
        )
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_APPLY, _apply, schema=APPLY_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Inicializa uma instalação do DVR."""
    client = IntelbrasClient(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
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
