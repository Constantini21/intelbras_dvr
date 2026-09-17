"""Cliente HTTP + descoberta de MAC para o DVR Intelbras/Dahua."""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Iterable
from typing import Optional

import httpx

from .const import (
    DEFAULT_HTTP_PORT,
    DEFAULT_RTSP_PORT,
    LOGIN_LOCKOUT_BACKOFF,
    MEDIAFILEFIND_CGI,
    RTSP_PLAYBACK_PATH,
    SNAPSHOT_CGI,
)

_LOGGER = logging.getLogger(__name__)

# porta discard: o datagrama é descartado, mas o kernel resolve o ARP
_ARP_PRIME_PORT = 9

# linhas "items[N].Campo=valor" (ou "items[N].Campo[i]=valor") do findNextFile
_ITEM_RE = re.compile(r"^items\[(\d+)\]\.([A-Za-z]+)(?:\[\d+\])?=(.*)$")
_FIND_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_PLAYBACK_TIME_FMT = "%Y_%m_%d_%H_%M_%S"
_FIND_PAGE_SIZE = 100


class RecordingsError(Exception):
    """Falha na consulta de gravações do DVR."""


@dataclass
class ProbeResult:
    """Resultado de validação de login."""

    ok: bool
    http_code: int
    size: int
    error: Optional[str] = None


@dataclass
class Recording:
    """Um segmento de gravação reportado pelo mediaFileFind."""

    channel: int  # como reportado pelo DVR (pode ser 0-based)
    start: datetime  # naive, horário local do DVR
    end: datetime
    file_path: str = ""
    length: int = 0  # bytes
    rec_type: str = "dav"
    flags: list[str] = field(default_factory=list)


class IntelbrasClient:
    """Wrapper sobre httpx com auth digest e helpers de MAC."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        http_port: int = DEFAULT_HTTP_PORT,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.http_port = http_port
        self._lockout_until = 0.0

    @property
    def base(self) -> str:
        if self.http_port and self.http_port != DEFAULT_HTTP_PORT:
            return f"http://{self.host}:{self.http_port}"
        return f"http://{self.host}"

    async def probe(self, channel: int = 1, timeout: float = 12.0) -> ProbeResult:
        """Tenta uma snapshot e devolve resultado estruturado."""
        loop = asyncio.get_running_loop()
        now = loop.time()
        if now < self._lockout_until:
            return ProbeResult(False, 0, 0, error="lockout local ativo")
        url = self.base + SNAPSHOT_CGI.format(channel=channel)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                auth=httpx.DigestAuth(self.username, self.password),
                verify=False,  # HTTP puro; evita carga bloqueante do bundle TLS no loop
            ) as cli:
                resp = await cli.get(url)
        except (httpx.TimeoutException, httpx.ConnectError) as ex:
            return ProbeResult(False, 0, 0, error=f"conexão: {ex}")
        except Exception as ex:  # noqa: BLE001
            return ProbeResult(False, 0, 0, error=f"erro: {ex}")

        size = len(resp.content)
        if resp.status_code == 401:
            # bloqueio provável: ativa backoff
            self._lockout_until = now + LOGIN_LOCKOUT_BACKOFF
            return ProbeResult(False, 401, size, error="401 (credencial ou banimento)")
        if resp.status_code != 200:
            return ProbeResult(False, resp.status_code, size, error=f"HTTP {resp.status_code}")
        if size < 1000:
            return ProbeResult(False, 200, size, error=f"snapshot vazio ({size}B)")
        # reset backoff em sucesso
        self._lockout_until = 0.0
        return ProbeResult(True, 200, size)

    async def snapshot(self, channel: int = 1, timeout: float = 12.0) -> Optional[bytes]:
        """Devolve bytes do JPEG, ou None."""
        loop = asyncio.get_running_loop()
        if loop.time() < self._lockout_until:
            return None
        url = self.base + SNAPSHOT_CGI.format(channel=channel)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                auth=httpx.DigestAuth(self.username, self.password),
                verify=False,  # HTTP puro; evita carga bloqueante do bundle TLS no loop
            ) as cli:
                resp = await cli.get(url)
            if resp.status_code == 200 and len(resp.content) >= 1000:
                return resp.content
            if resp.status_code == 401:
                self._lockout_until = loop.time() + LOGIN_LOCKOUT_BACKOFF
                _LOGGER.warning("DVR %s 401 — pausando %ss", self.host, LOGIN_LOCKOUT_BACKOFF)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("snapshot %s falhou: %s", self.host, ex)
        return None

    async def find_recordings(
        self,
        channel: int,
        start: datetime,
        end: datetime,
        timeout: float = 30.0,
    ) -> list[Recording]:
        """Lista gravações via mediaFileFind (create→findFile→findNextFile→close/destroy).

        `channel` é 1-based (mesma convenção do snapshot/RTSP); o DVR pode
        reportar items[].Channel 0-based, então o valor reportado não é usado
        para identificar o canal.
        """
        loop = asyncio.get_running_loop()
        if loop.time() < self._lockout_until:
            return []
        url = self.base + MEDIAFILEFIND_CGI
        recordings: list[Recording] = []
        async with httpx.AsyncClient(
            timeout=timeout,
            auth=httpx.DigestAuth(self.username, self.password),
            verify=False,  # HTTP puro; evita carga bloqueante do bundle TLS no loop
        ) as cli:
            resp = await cli.get(url, params={"action": "factory.create"})
            if resp.status_code == 401:
                self._lockout_until = loop.time() + LOGIN_LOCKOUT_BACKOFF
                raise RecordingsError("401 no factory.create (credencial ou banimento)")
            if resp.status_code != 200 or "=" not in resp.text:
                raise RecordingsError(
                    f"factory.create falhou: HTTP {resp.status_code} {resp.text[:80]!r}"
                )
            object_id = resp.text.strip().split("=", 1)[1].strip()
            try:
                # query montada à mão: o firmware exige espaço como %20 e o
                # httpx codificaria como "+", o que faz o DVR ignorar o filtro
                start_q = urllib.parse.quote(start.strftime(_FIND_TIME_FMT), safe=":")
                end_q = urllib.parse.quote(end.strftime(_FIND_TIME_FMT), safe=":")
                resp = await cli.get(
                    f"{url}?action=findFile&object={object_id}"
                    f"&condition.Channel={channel}"
                    f"&condition.StartTime={start_q}"
                    f"&condition.EndTime={end_q}"
                    f"&condition.Types%5B0%5D=dav"
                )
                # firmwares respondem "Error" quando não há resultados: não é falha
                if "OK" not in resp.text:
                    return []
                while True:
                    resp = await cli.get(
                        url,
                        params={
                            "action": "findNextFile",
                            "object": object_id,
                            "count": _FIND_PAGE_SIZE,
                        },
                    )
                    found, page = self._parse_find_page(resp.text)
                    recordings.extend(page)
                    if found < _FIND_PAGE_SIZE:
                        break
            finally:
                for action in ("close", "destroy"):
                    try:
                        await cli.get(url, params={"action": action, "object": object_id})
                    except Exception:  # noqa: BLE001
                        pass
        recordings.sort(key=lambda r: r.start)
        return recordings

    @staticmethod
    def _parse_find_page(text: str) -> tuple[int, list[Recording]]:
        """Converte a resposta key=value do findNextFile em Recordings."""
        found = 0
        raw: dict[int, dict[str, str]] = {}
        flags: dict[int, list[str]] = {}
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("found="):
                try:
                    found = int(line.split("=", 1)[1])
                except ValueError:
                    found = 0
                continue
            m = _ITEM_RE.match(line)
            if not m:
                continue
            idx, key, value = int(m.group(1)), m.group(2), m.group(3)
            if key == "Flags":
                flags.setdefault(idx, []).append(value)
            else:
                raw.setdefault(idx, {})[key] = value
        recordings: list[Recording] = []
        for idx, fields in sorted(raw.items()):
            try:
                recordings.append(
                    Recording(
                        channel=int(fields.get("Channel", 0)),
                        start=datetime.strptime(fields["StartTime"], _FIND_TIME_FMT),
                        end=datetime.strptime(fields["EndTime"], _FIND_TIME_FMT),
                        file_path=fields.get("FilePath", ""),
                        length=int(fields.get("Length", 0) or 0),
                        rec_type=fields.get("Type", "dav"),
                        flags=flags.get(idx, []),
                    )
                )
            except (KeyError, ValueError):
                # item malformado: pula sem derrubar a listagem
                continue
        return found, recordings

    def playback_rtsp_url(
        self,
        channel: int,
        start: datetime,
        end: datetime,
        rtsp_port: int = DEFAULT_RTSP_PORT,
    ) -> str:
        """URL RTSP de playback de um intervalo arbitrário."""
        user = urllib.parse.quote(self.username, safe="")
        pwd = urllib.parse.quote(self.password, safe="")
        path = RTSP_PLAYBACK_PATH.format(
            channel=channel,
            start=start.strftime(_PLAYBACK_TIME_FMT),
            end=end.strftime(_PLAYBACK_TIME_FMT),
        )
        return f"rtsp://{user}:{pwd}@{self.host}:{rtsp_port}{path}"


def _arp_table() -> dict[str, str]:
    """Mapa IP -> MAC da tabela ARP local, sem subprocesso."""
    table: dict[str, str] = {}
    try:
        with open("/proc/net/arp", encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                parts = line.split()
                # IP HWtype Flags HWaddress Mask Device; flags 0x0 = incompleto
                if len(parts) >= 4 and parts[2] != "0x0":
                    mac = parts[3].lower()
                    if mac != "00:00:00:00:00:00":
                        table[parts[0]] = mac
    except OSError as err:
        _LOGGER.debug("Não foi possível ler /proc/net/arp: %s", err)
    return table


def _arp_prime(targets: Iterable[str], pause: float) -> None:
    """Força a resolução ARP mandando um datagrama UDP para cada alvo.

    Um único socket para a varredura inteira. A versão anterior disparava um
    processo `ping` por host (254 por varredura): quando algum deles não
    terminava no timeout, os filhos ficavam sem reaproveitamento e os
    descritores vazavam até o Home Assistant morrer com EMFILE.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as err:
        _LOGGER.debug("ARP prime indisponível: %s", err)
        return
    try:
        sock.setblocking(False)
        for ip in targets:
            try:
                sock.sendto(b"", (ip, _ARP_PRIME_PORT))
            except OSError:
                continue
        time.sleep(pause)
    finally:
        sock.close()


def discover_mac(ip: str) -> Optional[str]:
    """Procura o MAC na tabela ARP local. Requer mesma L2/host network."""
    mac = _arp_table().get(ip)
    if mac:
        return mac
    _arp_prime([ip], pause=0.5)
    return _arp_table().get(ip)


def find_ip_by_mac(mac: str, subnet_prefix: Optional[str] = None) -> Optional[str]:
    """Procura o IP atual de um MAC, varrendo a /24 quando necessário."""
    mac = mac.lower()
    for ip, found in _arp_table().items():
        if found == mac:
            return ip

    if not subnet_prefix:
        return None

    _arp_prime((f"{subnet_prefix}.{i}" for i in range(1, 255)), pause=1.5)
    for ip, found in _arp_table().items():
        if found == mac:
            return ip
    return None
