"""Coordinator que rastreia IP do DVR por MAC e expõe last_result."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TRACK_BY_MAC,
    DATA_LAST_RESULT,
    DATA_MAC,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .dvr import IntelbrasClient, discover_mac, find_ip_by_mac

_LOGGER = logging.getLogger(__name__)


class IntelbrasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordena heartbeat + rastreio por MAC."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IntelbrasClient,
    ) -> None:
        self.entry = entry
        self.client = client
        interval = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval),
        )
        self._mac: str | None = entry.data.get(DATA_MAC)
        self._last_result: str = "(nunca executado)"
        self._track = entry.options.get(
            CONF_TRACK_BY_MAC, entry.data.get(CONF_TRACK_BY_MAC, True)
        )

    @property
    def mac(self) -> str | None:
        return self._mac

    @property
    def last_result(self) -> str:
        return self._last_result

    def set_last_result(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._last_result = f"[{ts}] {msg}"
        self.async_set_updated_data({**(self.data or {}), DATA_LAST_RESULT: self._last_result})

    async def _async_update_data(self) -> dict[str, Any]:
        """Tick: tenta descobrir/seguir MAC e ajustar host se mudou."""
        host = self.entry.data[CONF_HOST]
        data: dict[str, Any] = self.data.copy() if self.data else {}

        # Aprende MAC se ainda nao tem
        if self._mac is None:
            mac = await self.hass.async_add_executor_job(discover_mac, host)
            if mac:
                self._mac = mac
                self.hass.config_entries.async_update_entry(
                    self.entry, data={**self.entry.data, DATA_MAC: mac}
                )
                _LOGGER.info("MAC do DVR %s aprendido: %s", host, mac)

        # Rastreia por MAC: se IP mudou, atualiza entry
        if self._track and self._mac:
            prefix = ".".join(host.split(".")[:3]) if host.count(".") == 3 else None
            new_ip = await self.hass.async_add_executor_job(
                find_ip_by_mac, self._mac, prefix
            )
            if new_ip and new_ip != host:
                _LOGGER.warning(
                    "DVR (MAC %s) mudou de %s -> %s, atualizando entry",
                    self._mac,
                    host,
                    new_ip,
                )
                self.client.host = new_ip
                self.hass.config_entries.async_update_entry(
                    self.entry, data={**self.entry.data, CONF_HOST: new_ip}
                )
                self.set_last_result(
                    f"AUTO: IP {host} -> {new_ip} (MAC {self._mac})"
                )
                # reload pra forcar refresh das cameras
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.entry.entry_id)
                )
                data[CONF_HOST] = new_ip

        data[DATA_LAST_RESULT] = self._last_result
        data[DATA_MAC] = self._mac
        return data
