"""Constantes do componente intelbras_dvr."""
from __future__ import annotations

DOMAIN = "intelbras_dvr"
PLATFORMS = ["camera", "sensor"]

CONF_CHANNELS = "channels"
CONF_TRACK_BY_MAC = "track_by_mac"
CONF_RTSP_PORT = "rtsp_port"
CONF_RTSP_SUBTYPE = "rtsp_subtype"
CONF_HTTP_PORT = "http_port"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_USERNAME = "admin"
DEFAULT_CHANNELS = 4
DEFAULT_RTSP_PORT = 554
DEFAULT_RTSP_SUBTYPE = 0  # 0 = stream principal, 1 = substream
DEFAULT_HTTP_PORT = 80
DEFAULT_SCAN_INTERVAL = 300  # segundos

# CGI paths (compatível Intelbras/Dahua)
SNAPSHOT_CGI = "/cgi-bin/snapshot.cgi?channel={channel}"
MEDIAFILEFIND_CGI = "/cgi-bin/mediaFileFind.cgi"
RTSP_PATH = "/cam/realmonitor?channel={channel}&subtype={subtype}"
RTSP_PLAYBACK_PATH = "/cam/playback?channel={channel}&starttime={start}&endtime={end}"

# Media browser de gravações
MEDIA_BROWSE_DAYS = 7  # dias listados por canal
MEDIA_SLICE_MINUTES = 5  # granularidade dos trechos dentro de uma hora
HLS_MIME = "application/x-mpegURL"

# Estado armazenado em hass.data[DOMAIN][entry_id]
DATA_COORDINATOR = "coordinator"
DATA_LAST_RESULT = "last_result"
DATA_MAC = "mac"

# Backoff por bloqueio (após 401)
LOGIN_LOCKOUT_BACKOFF = 300  # 5 min
