"""Cliente HTTP + descoberta de MAC para o DVR Intelbras/Dahua."""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

import httpx

from .const import LOGIN_LOCKOUT_BACKOFF, SNAPSHOT_CGI

_LOGGER = logging.getLogger(__name__)

_MAC_RE = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.IGNORECASE)


@dataclass
class ProbeResult:
    """Resultado de validação de login."""

    ok: bool
    http_code: int
    size: int
    error: Optional[str] = None


class IntelbrasClient:
    """Wrapper sobre httpx com auth digest e helpers de MAC."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self._lockout_until = 0.0

    @property
    def base(self) -> str:
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


def discover_mac(ip: str) -> Optional[str]:
    """Procura o MAC na tabela ARP local. Requer mesma L2/host network."""
    try:
        subprocess.run(
            ["ping", "-c1", "-W1", ip],
            check=False,
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        out = subprocess.run(
            ["ip", "neigh", "show", ip],
            check=False,
            timeout=3,
            capture_output=True,
            text=True,
        ).stdout
        m = _MAC_RE.search(out)
        if m:
            return m.group(0).lower()
        # fallback: /proc/net/arp
        try:
            with open("/proc/net/arp", encoding="utf-8") as fh:
                for line in fh.readlines()[1:]:
                    parts = line.split()
                    if parts and parts[0] == ip:
                        return parts[3].lower()
        except OSError:
            pass
    except Exception as ex:  # noqa: BLE001
        _LOGGER.debug("discover_mac(%s) falhou: %s", ip, ex)
    return None


def find_ip_by_mac(mac: str, subnet_prefix: Optional[str] = None) -> Optional[str]:
    """Procura o IP atual de um MAC fazendo arp sweep opcional."""
    mac = mac.lower()
    # tentativa 1: tabela ARP atual
    try:
        out = subprocess.run(
            ["ip", "-4", "neigh", "show"],
            check=False,
            timeout=3,
            capture_output=True,
            text=True,
        ).stdout
        for line in out.splitlines():
            if mac in line.lower() and " FAILED" not in line and " INCOMPLETE" not in line:
                return line.split()[0]
    except Exception:  # noqa: BLE001
        pass

    # tentativa 2: ARP sweep (se prefixo fornecido)
    if subnet_prefix:
        procs = [
            subprocess.Popen(
                ["ping", "-c1", "-W1", f"{subnet_prefix}.{i}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for i in range(1, 255)
        ]
        for p in procs:
            p.wait(timeout=3)
        try:
            out = subprocess.run(
                ["ip", "-4", "neigh", "show"],
                check=False,
                timeout=3,
                capture_output=True,
                text=True,
            ).stdout
            for line in out.splitlines():
                if mac in line.lower() and " FAILED" not in line:
                    return line.split()[0]
        except Exception:  # noqa: BLE001
            pass
    return None
