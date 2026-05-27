# Intelbras DVR

Integração customizada do Home Assistant para DVRs **Intelbras / Dahua** com:

- 🎥 Câmeras via snapshot HTTP (digest) + stream RTSP — uma entidade por canal.
- 🔧 Reautenticação via UI: serviço `intelbras_dvr.apply_credentials` para trocar
  IP/usuário/senha sem recriar a integração.
- 🌐 **Auto-rastreio por MAC**: se o DHCP der outro IP ao DVR (queda de energia,
  reboot do roteador), a integração detecta o MAC original e atualiza o host
  automaticamente — sem ação manual.
- 📋 Sensor `last_apply_result` com o resultado da última (re)autenticação.

Inspirado no padrão `generic_camera` mas dedicado a DVRs Intelbras/Dahua,
incluindo o problema clássico de bloqueio de login após várias tentativas
erradas (a integração desabilita auto-reload em caso de 401 repetido).

## Instalação

### Via HACS (recomendado)
1. HACS → menu (⋮) → **Custom repositories**.
2. URL: `https://github.com/Constantini21/intelbras_dvr` (categoria *Integration*).
3. Instalar **Intelbras DVR** e reiniciar o HA.
4. Settings → Devices & Services → **Add Integration** → "Intelbras DVR".

### Manual
Copie `custom_components/intelbras_dvr/` para
`<config>/custom_components/intelbras_dvr/` e reinicie o HA.

## Configuração (config flow)

| Campo | Default | Descrição |
|-------|---------|-----------|
| `host` | — | IP do DVR (ex: `172.16.0.12`) |
| `username` | `admin` | Usuário do DVR |
| `password` | — | Senha do DVR |
| `channels` | `4` | Quantidade de canais a criar |
| `track_by_mac` | `true` | Habilitar rastreio automático por MAC |

Ao salvar, a integração testa `GET http://<host>/cgi-bin/snapshot.cgi?channel=1`
com digest auth. Se 200, cria N câmeras.

## Serviço `intelbras_dvr.apply_credentials`

```yaml
service: intelbras_dvr.apply_credentials
data:
  entry_id: <config_entry_id>   # opcional se só houver 1 instalação
  host: 172.16.0.12
  username: admin
  password: nova-senha
```

Valida, atualiza a entry, faz reload sem reiniciar o HA.

## Auto-rastreio por MAC

Quando ativado:
- A cada `scan_interval` (default 300s) a integração lê a tabela ARP local
  (`ip neigh`) e localiza o MAC associado ao IP atual.
- Em ciclos seguintes, se o IP do MAC mudar, a entry é atualizada e
  recarregada automaticamente.
- Funciona **apenas** se o HA roda em `network_mode: host` (ou bare metal) —
  containers em `bridge` não enxergam a ARP do host.

## Sensor `last_apply_result`

Mostra o resultado da última chamada do serviço ou do auto-rastreio
(`OK: ...` ou `FAIL: ...`).

## Limitações conhecidas

- DVRs Intelbras/Dahua bloqueiam o IP cliente por ~30min após 3-5 tentativas
  de login erradas. A integração detecta 401 e pausa retentativas de stream
  por 5min para não agravar o ban.
- Só descobre MAC se o HA estiver na mesma L2 do DVR.
