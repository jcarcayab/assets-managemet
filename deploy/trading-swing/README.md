# Deployment: trading-swing host

Patrimonio runs next to the swing stack on `ubuntu@10.8.0.1` (EC2, reachable through the OpenVPN at
`10.8.0.1`), fully independent from it: its own compose project (`patrimonio`), its own Caddy, SQLite.

**URL:** https://10.8.0.1:8443 — only through the VPN. Caddy binds the VPN address only, so the app is not
reachable from the public IP even if the security group allowed the port.

| Container | Role | Memory limit |
|---|---|---|
| `patrimonio-web` | gunicorn (1 worker, 4 threads), API + built React app, on `127.0.0.1:8090` | 450 MB |
| `patrimonio-scheduler` | hourly prices; daily after 21:00 UTC: Plaid sync + snapshot | 350 MB |
| `patrimonio-caddy` | TLS on `10.8.0.1:8443` (host network), internal CA | 64 MB |

The box has ~2 GB RAM shared with swing — keep the single worker and the limits.

## Deploy

```bash
deploy/trading-swing/deploy.sh          # build frontend locally, rsync, docker compose build + up
deploy/trading-swing/deploy.sh --logs   # same, then follow logs
```

SSH uses the **"Personal"** key from the 1Password agent. If the agent offers too many keys
("Too many authentication failures"), export its public key once and point the script at it:

```bash
SSH_AUTH_SOCK=~/Library/Group\ Containers/2BUA8C4S2C.com.1password/t/agent.sock ssh-add -L | grep ' Personal$' > ~/.ssh/personal.pub
DEPLOY_KEY=~/.ssh/personal.pub deploy/trading-swing/deploy.sh
```

Server-side state lives in `~/patrimonio/deploy/trading-swing/` and is never touched by `rsync`:
`.env` (production settings, mode 600) and `data/db.sqlite3`.

## Trust the HTTPS certificate (once per device)

Caddy issues the certificate from its own local CA (there's no public DNS name for Let's Encrypt). The root
lives in the `patrimonio_caddy-data` volume, valid until 2036. Get it with:

```bash
ssh ubuntu@10.8.0.1 'docker exec patrimonio-caddy cat /data/caddy/pki/authorities/local/root.crt' > patrimonio-root-ca.crt
```

- **macOS:** double-click the `.crt` → Keychain Access → open "Caddy Local Authority - 2026 ECC Root" →
  Trust → "Always Trust".
- **iPhone:** AirDrop the `.crt` → Settings → *Profile Downloaded* → Install; then Settings → General →
  About → Certificate Trust Settings → enable it.

Check the SHA-256 fingerprint before trusting it:
`11:CF:40:04:0C:6D:7F:93:26:47:9F:CD:FE:0D:DD:4A:8A:8F:F4:53:39:8E:9B:A5:BC:E0:C4:0B:92:F4:91:44`.
Removing the `patrimonio_caddy-data` volume creates a new CA, and every device must trust it again.

## Install as an app (iPad, iPhone, Mac)

Patrimonio is a PWA: no App Store. With the VPN on and the certificate trusted (above):

- **iPad / iPhone:** open `https://10.8.0.1:8443` in **Safari** → Share → *Add to Home Screen*. It opens
  fullscreen with its own icon. (Only Safari can install it on iOS.)
- **Mac:** Safari → File → *Add to Dock*, or Chrome/Edge → the install icon in the address bar.

The installed app caches only the interface (JS, CSS, fonts), so it opens instantly; the data always comes
from the server, so it still needs the VPN. New versions install themselves on the next launch after a deploy.

## Operations

```bash
ssh ubuntu@10.8.0.1
cd ~/patrimonio/deploy/trading-swing
docker compose ps
docker compose logs -f web                       # or scheduler / caddy
docker compose exec web python manage.py changepassword juan
docker compose exec web python manage.py shell   # e.g. reset someone's 2FA: TOTPDevice.objects.filter(user__username=…).delete()
cp data/db.sqlite3 ~/patrimonio-$(date +%F).sqlite3   # manual copy of all data
```

## Notes

- `.env` reuses the development `SECRET_KEY` and pins `FIELD_ENCRYPTION_KEY` to it, because the copied
  database holds a 2FA secret and recovery codes derived from it. Don't change either value.
- Plaid OAuth banks (production only) would use `PLAID_REDIRECT_URI=https://10.8.0.1:8443/conexiones`,
  registered in the Plaid dashboard.
