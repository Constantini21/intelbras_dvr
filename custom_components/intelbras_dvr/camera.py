"""Plataforma camera para canais do DVR."""
from __future__ import annotations

import urllib.parse

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CHANNELS,
    CONF_RTSP_PORT,
    DATA_COORDINATOR,
    DEFAULT_CHANNELS,
    DEFAULT_RTSP_PORT,
    DOMAIN,
    RTSP_PATH,
)
from .coordinator import IntelbrasCoordinator
from .dvr import IntelbrasClient


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: IntelbrasCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    client: IntelbrasClient = hass.data[DOMAIN][entry.entry_id]["client"]
    channels = entry.options.get(
        CONF_CHANNELS, entry.data.get(CONF_CHANNELS, DEFAULT_CHANNELS)
    )
    entities = [
        IntelbrasCamera(entry, coord, client, ch) for ch in range(1, channels + 1)
    ]
    async_add_entities(entities)


class IntelbrasCamera(Camera):
    """Câmera de um canal do DVR."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_brand = "Intelbras"

    def __init__(
        self,
        entry: ConfigEntry,
        coord: IntelbrasCoordinator,
        client: IntelbrasClient,
        channel: int,
    ) -> None:
        super().__init__()
        self._entry = entry
        self._coord = coord
        self._client = client
        self._channel = channel
        self._attr_unique_id = f"{entry.entry_id}_ch{channel}"
        self._attr_name = f"DVR Canal {channel}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "Intelbras",
            "model": "DVR (Dahua-compatible)",
            "configuration_url": f"http://{self._entry.data[CONF_HOST]}",
            "connections": (
                {("mac", self._coord.mac)} if self._coord.mac else set()
            ),
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # mantém client em sync com a entry (caso IP/cred tenha mudado)
        self._client.host = self._entry.data[CONF_HOST]
        self._client.username = self._entry.data[CONF_USERNAME]
        self._client.password = self._entry.data[CONF_PASSWORD]
        return await self._client.snapshot(self._channel)

    async def stream_source(self) -> str | None:
        user = urllib.parse.quote(self._entry.data[CONF_USERNAME], safe="")
        pwd = urllib.parse.quote(self._entry.data[CONF_PASSWORD], safe="")
        host = self._entry.data[CONF_HOST]
        port = self._entry.options.get(
            CONF_RTSP_PORT, self._entry.data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)
        )
        return (
            f"rtsp://{user}:{pwd}@{host}:{port}"
            + RTSP_PATH.format(channel=self._channel)
        )
