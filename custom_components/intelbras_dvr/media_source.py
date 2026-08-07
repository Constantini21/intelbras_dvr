"""Media source: gravações do DVR via mediaFileFind + playback RTSP→HLS."""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from homeassistant.components.camera import DynamicStreamSettings
from homeassistant.components.media_player import MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.components.stream import create_stream
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHANNELS,
    CONF_RTSP_PORT,
    DEFAULT_CHANNELS,
    DEFAULT_RTSP_PORT,
    DOMAIN,
    HLS_MIME,
    MEDIA_BROWSE_DAYS,
    MEDIA_SLICE_MINUTES,
)
from .dvr import IntelbrasClient, RecordingsError

_LOGGER = logging.getLogger(__name__)

_COMPACT_FMT = "%Y%m%d%H%M%S"
_DAY_FMT = "%Y%m%d"


async def async_get_media_source(hass: HomeAssistant) -> "IntelbrasMediaSource":
    """Registra a fonte de mídia do DVR."""
    return IntelbrasMediaSource(hass)


class IntelbrasMediaSource(MediaSource):
    """Gravações do DVR: canais → dias → horas → trechos."""

    name = "Intelbras DVR"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    def _entries(self) -> list[ConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id in self.hass.data.get(DOMAIN, {})
        ]

    def _client(self, entry_id: str) -> tuple[ConfigEntry, IntelbrasClient]:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if entry is None or not data or "client" not in data:
            raise Unresolvable("DVR não está carregado")
        return entry, data["client"]

    @staticmethod
    def _opt(entry: ConfigEntry, key: str, default):
        return entry.options.get(key, entry.data.get(key, default))

    # ---------- reprodução ----------

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        parts = (item.identifier or "").split("|")
        if len(parts) != 5 or parts[0] != "PLAY":
            raise Unresolvable(f"Identificador inválido: {item.identifier}")
        _, entry_id, channel, start_s, end_s = parts
        entry, client = self._client(entry_id)
        try:
            start = datetime.strptime(start_s, _COMPACT_FMT)
            end = datetime.strptime(end_s, _COMPACT_FMT)
        except ValueError as ex:
            raise Unresolvable(f"Intervalo inválido: {item.identifier}") from ex
        rtsp_port = self._opt(entry, CONF_RTSP_PORT, DEFAULT_RTSP_PORT)
        url = client.playback_rtsp_url(int(channel), start, end, rtsp_port)
        stream = create_stream(self.hass, url, {}, DynamicStreamSettings())
        stream.add_provider("hls", timeout=300)
        stream_url = stream.endpoint_url("hls").replace("master_", "")
        return PlayMedia(stream_url, HLS_MIME)

    # ---------- navegação ----------

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        identifier = item.identifier or ""
        if not identifier:
            return self._browse_root()
        kind = identifier.split("|")[0]
        if kind == "CH":
            return self._browse_channels(identifier)
        if kind == "DAY":
            return self._browse_days(identifier)
        if kind == "FILES":
            return await self._browse_hours(identifier)
        if kind == "HOUR":
            return await self._browse_slices(identifier)
        raise Unresolvable(f"Caminho desconhecido: {identifier}")

    def _browse_root(self) -> BrowseMediaSource:
        entries = self._entries()
        if not entries:
            raise Unresolvable("Nenhum DVR configurado")
        if len(entries) == 1:
            return self._browse_channels(f"CH|{entries[0].entry_id}")
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title="Intelbras DVR",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"CH|{entry.entry_id}",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type="",
                    title=entry.title,
                    can_play=False,
                    can_expand=True,
                )
                for entry in entries
            ],
        )

    def _browse_channels(self, identifier: str) -> BrowseMediaSource:
        _, entry_id = identifier.split("|")
        entry, _ = self._client(entry_id)
        channels = self._opt(entry, CONF_CHANNELS, DEFAULT_CHANNELS)
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=entry.title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=f"DAY|{entry_id}|{channel}",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type="",
                    title=f"DVR Canal {channel}",
                    can_play=False,
                    can_expand=True,
                )
                for channel in range(1, channels + 1)
            ],
        )

    def _browse_days(self, identifier: str) -> BrowseMediaSource:
        _, entry_id, channel = identifier.split("|")
        self._client(entry_id)
        today = dt_util.now().date()
        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"FILES|{entry_id}|{channel}|{day.strftime(_DAY_FMT)}",
                media_class=MediaClass.DIRECTORY,
                media_content_type="",
                title=day.strftime("%d/%m/%Y"),
                can_play=False,
                can_expand=True,
                children_media_class=MediaClass.VIDEO,
            )
            for day in (today - timedelta(days=n) for n in range(MEDIA_BROWSE_DAYS))
        ]
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=f"DVR Canal {channel}",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=children,
        )

    async def _day_recordings(self, entry_id: str, channel: str, day_s: str):
        _, client = self._client(entry_id)
        day = datetime.strptime(day_s, _DAY_FMT).date()
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max.replace(microsecond=0))
        try:
            recordings = await client.find_recordings(int(channel), start, end)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.warning("Listagem de gravações falhou: %s", ex)
            raise Unresolvable("DVR indisponível") from ex
        return day, recordings

    async def _browse_hours(self, identifier: str) -> BrowseMediaSource:
        """Um dia: pastas por hora, só das horas com gravação."""
        _, entry_id, channel, day_s = identifier.split("|")
        day, recordings = await self._day_recordings(entry_id, channel, day_s)
        hours = sorted(
            {
                hour
                for rec in recordings
                # última hora coberta: a do instante final menos 1s
                # (gravação terminando exatamente em HH:00:00 não cobre HH)
                for hour in range(
                    rec.start.hour, (rec.end - timedelta(seconds=1)).hour + 1
                )
            }
        )
        children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"HOUR|{entry_id}|{channel}|{day_s}|{hour:02d}",
                media_class=MediaClass.DIRECTORY,
                media_content_type="",
                title=f"{hour:02d}:00 – {hour:02d}:59",
                can_play=False,
                can_expand=True,
                children_media_class=MediaClass.VIDEO,
            )
            for hour in hours
        ]
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=day.strftime("%d/%m/%Y"),
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=children,
        )

    async def _browse_slices(self, identifier: str) -> BrowseMediaSource:
        """Uma hora: trechos de MEDIA_SLICE_MINUTES min cobertos por gravação."""
        _, entry_id, channel, day_s, hour_s = identifier.split("|")
        day, recordings = await self._day_recordings(entry_id, channel, day_s)
        hour = int(hour_s)
        hour_start = datetime.combine(day, time(hour=hour))
        hour_end = hour_start + timedelta(hours=1)
        step = timedelta(minutes=MEDIA_SLICE_MINUTES)
        children = []
        slot = hour_start
        while slot < hour_end:
            slot_end = slot + step
            if any(rec.start < slot_end and rec.end > slot for rec in recordings):
                children.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier=(
                            f"PLAY|{entry_id}|{channel}"
                            f"|{slot.strftime(_COMPACT_FMT)}"
                            f"|{slot_end.strftime(_COMPACT_FMT)}"
                        ),
                        media_class=MediaClass.VIDEO,
                        media_content_type=MediaType.VIDEO,
                        title=f"{slot.strftime('%H:%M')} – {slot_end.strftime('%H:%M')}",
                        can_play=True,
                        can_expand=False,
                    )
                )
            slot = slot_end
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=f"{day.strftime('%d/%m/%Y')} {hour:02d}h",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.VIDEO,
            children=children,
        )
