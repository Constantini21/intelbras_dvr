"""Aplica credenciais/IP do DVR e atualiza câmeras generic existentes."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DATA_MAC, DOMAIN
from .dvr import IntelbrasClient, discover_mac

_LOGGER = logging.getLogger(__name__)

_HA_FIX_OVERRIDES = "/config/ha_fix_overrides.json"
_LAST_RESULT_FILE = "/config/dvr_last_result.txt"
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_EMBEDDED_AUTH_RE = re.compile(r"://[^@/]+@")


@dataclass
class ApplyOutcome:
    """Resultado consolidado da aplicação de credenciais."""

    ok: bool
    message: str
    mac: str | None = None
    generic_updated: int = 0
    integration_updated: bool = False
    needs_restart: bool = False


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _format_result(message: str) -> str:
    return f"[{_timestamp()}] {message}"


def _write_last_result(message: str) -> None:
    try:
        Path(_LAST_RESULT_FILE).write_text(_format_result(message), encoding="utf-8")
    except OSError as err:
        _LOGGER.debug("Não foi possível gravar %s: %s", _LAST_RESULT_FILE, err)


def _write_mac_override(mac: str) -> None:
    path = Path(_HA_FIX_OVERRIDES)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["dvr_mac"] = mac.lower()
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as err:
        _LOGGER.warning("Não foi possível gravar override MAC em %s: %s", path, err)


def _normalize_url(url: str, host: str) -> str:
    cleaned = _EMBEDDED_AUTH_RE.sub("://", url)
    return _IP_RE.sub(host, cleaned)


def _patch_generic_cameras(
    hass: HomeAssistant, host: str, username: str | None, password: str | None
) -> list[str]:
    updated: list[str] = []
    for entry in hass.config_entries.async_entries("generic"):
        options = dict(entry.options)
        blob = " ".join(str(v) for v in options.values())
        if "snapshot.cgi" not in blob and "rtsp://" not in blob:
            continue

        new_options = dict(options)
        changed = False
        for key in ("still_image_url", "stream_source"):
            value = options.get(key)
            if not value:
                continue
            normalized = _normalize_url(str(value), host)
            if normalized != value:
                new_options[key] = normalized
                changed = True

        if username and options.get(CONF_USERNAME) != username:
            new_options[CONF_USERNAME] = username
            changed = True
        if password and options.get(CONF_PASSWORD) != password:
            new_options[CONF_PASSWORD] = password
            changed = True

        if not changed:
            continue

        hass.config_entries.async_update_entry(entry, options=new_options)
        if entry.disabled_by:
            hass.config_entries.async_update_entry(entry, disabled_by=None)
        updated.append(entry.entry_id)
    return updated


async def async_sync_generic_cameras(
    hass: HomeAssistant,
    host: str,
    username: str | None = None,
    password: str | None = None,
) -> int:
    """Aponta as câmeras generic do DVR para o host atual e recarrega as alteradas.

    Substitui o antigo restart do HA: reload das entries é suficiente e
    não derruba o resto da casa.
    """
    updated = _patch_generic_cameras(hass, host, username, password)
    for entry_id in updated:
        hass.async_create_task(hass.config_entries.async_reload(entry_id))
    return len(updated)


async def apply_credentials(
    hass: HomeAssistant,
    host: str,
    username: str,
    password: str,
    entry: ConfigEntry | None = None,
) -> ApplyOutcome:
    """Valida credenciais, aprende MAC e aplica nas câmeras/integração."""
    client = IntelbrasClient(host, username, password)
    probe = await client.probe()
    if not probe.ok:
        message = f"FAIL: {probe.error} (HTTP={probe.http_code})"
        _write_last_result(message)
        return ApplyOutcome(False, message)

    mac = await hass.async_add_executor_job(discover_mac, host)
    if mac:
        await hass.async_add_executor_job(_write_mac_override, mac)

    generic_updated = await async_sync_generic_cameras(hass, host, username, password)
    integration_updated = False

    if entry is not None:
        new_data = {
            **entry.data,
            CONF_HOST: host,
            CONF_USERNAME: username,
            CONF_PASSWORD: password,
        }
        if mac:
            new_data[DATA_MAC] = mac
        hass.config_entries.async_update_entry(entry, data=new_data)
        integration_updated = True
        coord = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get(DATA_COORDINATOR)
        if coord is not None:
            coord.client.host = host
            coord.client.username = username
            coord.client.password = password
            if mac:
                coord._mac = mac  # noqa: SLF001
            coord.set_last_result(
                f"OK: {host} validado"
                + (f" (MAC {mac})" if mac else " (MAC desconhecido)")
            )

    if generic_updated:
        message = (
            f"OK: {host} login ok"
            + (f", MAC {mac}" if mac else ", MAC não descoberto")
            + f", {generic_updated} câmeras atualizadas"
        )
    elif integration_updated:
        message = (
            f"OK: {host} validado"
            + (f" (MAC {mac})" if mac else " (MAC desconhecido)")
        )
    else:
        message = (
            f"OK: {host} login ok"
            + (f", MAC {mac}" if mac else "")
            + ", nenhuma câmera precisou de alteração"
        )

    _write_last_result(message)
    return ApplyOutcome(
        ok=True,
        message=message,
        mac=mac,
        generic_updated=generic_updated,
        integration_updated=integration_updated,
        needs_restart=False,
    )
