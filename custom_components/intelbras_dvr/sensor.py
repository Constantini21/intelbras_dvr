"""Sensor com o último resultado de apply/auto-tracking."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DATA_LAST_RESULT, DATA_MAC, DOMAIN
from .coordinator import IntelbrasCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: IntelbrasCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([LastResultSensor(entry, coord)])


class LastResultSensor(CoordinatorEntity[IntelbrasCoordinator], SensorEntity):
    """Mostra o último OK/FAIL/AUTO."""

    _attr_icon = "mdi:message-text-clock"
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coord: IntelbrasCoordinator) -> None:
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_result"
        self._attr_name = "Último resultado"

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get(DATA_LAST_RESULT, "—")[:255]

    @property
    def extra_state_attributes(self) -> dict:
        return {"mac": (self.coordinator.data or {}).get(DATA_MAC)}

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "Intelbras",
            "model": "DVR (Dahua-compatible)",
        }
