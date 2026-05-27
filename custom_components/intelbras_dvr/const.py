"""Constantes do componente intelbras_dvr."""
from __future__ import annotations

DOMAIN = "intelbras_dvr"
PLATFORMS = ["camera", "sensor"]

CONF_CHANNELS = "channels"
CONF_TRACK_BY_MAC = "track_by_mac"
CONF_RTSP_PORT = "rtsp_port"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_USERNAME = "admin"
DEFAULT_CHANNELS = 4
DEFAULT_RTSP_PORT = 554
DEFAULT_SCAN_INTERVAL = 300  # segundos

# CGI paths (compatível Intelbras/Dahua)
SNAPSHOT_CGI = "/cgi-bin/snapshot.cgi?channel={channel}"
RTSP_PATH = "/cam/realmonitor?channel={channel}&subtype=0"

# Estado armazenado em hass.data[DOMAIN][entry_id]
DATA_COORDINATOR = "coordinator"
DATA_LAST_RESULT = "last_result"
DATA_MAC = "mac"

# Backoff por bloqueio (após 401)
LOGIN_LOCKOUT_BACKOFF = 300  # 5 min
