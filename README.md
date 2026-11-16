# Telegram relay

Small, stateless FastAPI bridge: **PC → your VPS → api.telegram.org**.
This is for the Telegram **Bot API**, not personal-account MTProto clients.
Your VPS must be able to reach Telegram over HTTPS.

## Deploy on your VPS

Install Docker Engine with the Compose plugin, then copy this folder to the VPS.

```sh
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Paste the generated value into RELAY_API_KEY in .env.
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

The service binds to localhost. To reach it securely from your PC, choose either:

### HTTPS with a domain

Point a domain's DNS to your VPS. Replace `relay.example.com` in `Caddyfile` with
that domain. Allow inbound TCP ports 80 and 443; Caddy obtains an HTTPS certificate.

```sh
docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

If you already have an HTTPS reverse proxy, forward it to `127.0.0.1:8000`
instead. Allow at least 130 seconds for upstream reads for long polling and
configure upload size limits to suit your files. Avoid logging request URLs:
Telegram puts bot tokens in the path. Container access logging is disabled.

### SSH tunnel without a domain

Run this on your PC and keep it open:

```sh
ssh -N -L 8000:127.0.0.1:8000 user@YOUR_VPS_IP
```

Use `http://127.0.0.1:8000` as the relay URL. The SSH connection encrypts traffic.

## Use from your PC

Replace Telegram's origin with your relay URL and add `X-API-Key` to each request.
Use your real bot token in place of `123456:YOUR_BOT_TOKEN`.

```sh
curl https://relay.example.com/bot123456:YOUR_BOT_TOKEN/getMe \
  -H "X-API-Key: YOUR_RELAY_API_KEY"

curl https://relay.example.com/bot123456:YOUR_BOT_TOKEN/sendMessage \
  -H "X-API-Key: YOUR_RELAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"chat_id":123456789,"text":"Hello from my VPS relay"}'

curl https://relay.example.com/bot123456:YOUR_BOT_TOKEN/sendDocument \
  -H "X-API-Key: YOUR_RELAY_API_KEY" \
  -F 'chat_id=123456789' -F 'document=@example.pdf'
```

Python example (install `httpx` on your PC):

```python
import os
import httpx

base = os.environ['RELAY_URL']  # https://relay.example.com or SSH tunnel URL
token = os.environ['TELEGRAM_BOT_TOKEN']
with httpx.Client(headers={'X-API-Key': os.environ['RELAY_API_KEY']}, timeout=120) as client:
    response = client.post(f'{base}/bot{token}/sendMessage', json={
        'chat_id': 123456789,
        'text': 'Hello through the VPS!',
    })
    response.raise_for_status()
    print(response.json())
```

## Contract

### Current VPS deployment

The production URL is `https://relay.jetourtools.com`. The checkout lives at
`/home/ubuntu/apps/telegram_relay`; its private `.env` stores the API key.
The existing `webadb-nginx-1` container terminates HTTPS on port 443 and reaches
the relay through the external `webadb_default` Docker network.

```sh
cd ~/apps/telegram_relay
docker compose -f compose.yaml -f compose.nginx.yaml up -d --build
```

The relay server blocks in `deploy/` are appended to the existing Nginx template
and its rendered configuration. Backups are in `nginx-backup-*` on the VPS.
`deploy/install-nginx.sh` is a first-install script; it refuses to duplicate a
configured domain. Existing Certbot handles renewal; a user cron job checks the
relay certificate hourly and gracefully reloads Nginx only if it changes.
Retrieve the relay API key privately over SSH from `.env`; do not commit it.

- `GET /health`: unauthenticated process health; does not check Telegram connectivity.
- `GET|POST /bot<TOKEN>/<METHOD>`: forward query and raw body to Telegram.
- `GET /file/bot<TOKEN>/<FILE_PATH>`: stream a file using the path from `getFile`.
- All relay routes require `X-API-Key`. Missing/incorrect key returns 401.
- JSON, form and multipart bodies pass through unchanged. Responses preserve
  Telegram's status and body, including errors and rate limits.
- Connection failures return 502; timeouts before response headers return 504.
  A failure after streaming starts interrupts the response. No automatic retries:
  retrying a timed-out write may send a message twice.
- Upstream read/write inactivity timeout is 120 seconds; use a smaller `getUpdates`
  polling timeout (for example 50 seconds). Uploads and downloads stream in memory
  chunks. Telegram's own file limits still apply.
- Only api.telegram.org is reachable through the relay; redirects are not followed.
- No webhook receiver or webhook forwarding is included. Use `getUpdates` to poll.
  SDK clients must support setting both custom API/file origins and the API-key header.

Telegram contract reference: https://core.telegram.org/bots/api

## Local checks

```sh
python -m venv .venv
# Linux: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m unittest discover -s tests -v
```
