# bbv2 — Deployment & CI/CD

How briefbot runs in production and how code gets there. This is the runbook —
read it before touching the server.

## TL;DR

- **App:** `https://briefbot.tailb058fe.ts.net` — a headless Ubuntu VM on a home
  Proxmox box, reachable **only over Tailscale** (the family's tailnet).
- **Deploy:** `git push` to `main` → a **self-hosted GitHub Actions runner on the
  VM** rebuilds and restarts the app (~30 s). No manual steps, no exposed ports.
- **Everything is boot-persistent** (systemd) — a VM reboot brings the whole stack
  back on its own.

## Infrastructure

```
  Internet ──✗ (not exposed)
                    Tailscale tailnet (briefbot.tailb058fe.ts.net)
  family devices ───────────────┐
                                ▼
  Proxmox host "dev" 10.0.0.8 ── VM 200 "briefbot" (10.0.0.224 / tailscale 100.121.155.88)
                                   Ubuntu 24.04 · 2 vCPU · 4 GB · 40 GB on ZFS "fastpool"
```

- **Proxmox host:** `dev` at `10.0.0.8:8006` (single node). Managed from Claude
  Code via the **ProxmoxMCP-Plus** MCP server (least-priv API token `claude@pve!mcp`).
- **VM 200 `briefbot`:** Ubuntu 24.04, SSH user **`briefbot`** (key-only;
  passwordless sudo via `/etc/sudoers.d/90-briefbot`). App lives in
  `/home/briefbot/briefbot`.

## Runtime topology (on the VM)

```
 Tailscale (HTTPS :443, auto cert)
        │  tailscale serve  →  http://127.0.0.1:8081
        ▼
 nginx :8081  ──  serves dashboard/dist/ (static SPA)
        │         proxies /api/  →  127.0.0.1:8080   (buffering off, 600s read → SSE)
        ▼
 systemd "bbv2"  =  uvicorn (FastAPI) on 127.0.0.1:8080
        │            consumer API (/health /topics /items) + dashboard API (/api/*)
        ▼
 SQLite  /home/briefbot/briefbot/data/bbv2.db  (WAL)

 cron (briefbot):  bbv2 tick  @ :07 hourly   ·  bbv2 nightly @ 23:00
```

| Service | Unit / mechanism | Role |
|---|---|---|
| Backend | `systemd bbv2` → `.venv/bin/python -m bbv2 serve --host 127.0.0.1 --port 8080` | FastAPI app (consumer + dashboard API) |
| Web | `nginx` site `bbv2` on `127.0.0.1:8081` | serve built SPA + reverse-proxy `/api/` |
| TLS / ingress | `tailscale serve --bg http://127.0.0.1:8081` | HTTPS on the tailnet name (auto cert) |
| Cron | `briefbot` crontab | hourly `tick` (pull) + nightly `nightly` (briefs+email) |
| Deploy | `systemd actions.runner.migoVanDingo-briefbot.briefbot-vm` | GitHub Actions self-hosted runner |

All five are `systemctl enable`d (or persist their own config) → survive reboot.

## Access & auth

- **Reaching the app:** install Tailscale on the device, join the tailnet, browse
  to `https://briefbot.tailb058fe.ts.net`. Not on the public internet (`tailscale
  serve`, not `funnel`).
- **HTTPS:** Tailscale terminates TLS with a valid cert for the `*.ts.net` name
  (needs "HTTPS Certificates" enabled in the Tailscale admin). nginx + the app
  speak plain HTTP behind it on loopback.
- **App login:** Firebase Auth (Google + email/password), project **`briefbot-v2`**.
  The serving host **must** be in Firebase Console → Authentication → Settings →
  **Authorized domains** (`briefbot.tailb058fe.ts.net` is added). Firebase rejects
  auth from unlisted domains — this is the #1 "can't log in" cause.
- **Admin:** owner-only via `ADMIN_EMAILS` in the backend `.env` (no UI/API to
  grant). That's the only way to get `/admin`.

## Configuration & secrets (live only on the VM)

Gitignored — **never committed**, transferred from the Mac dev setup, preserved
across deploys by the rsync excludes:

- `/home/briefbot/briefbot/.env` (chmod 600) — `FIREBASE_CONFIG` (path to the
  service-account JSON), `ANTHROPIC_API_KEY`, `GROK_API_KEY`, `BRAVESEARCH_API_KEY`,
  `MAILGUN_*`, `ADMIN_EMAILS`, plus VM-specific:
  `BBV2_SERVE_HOST=127.0.0.1`, `ALLOWED_ORIGINS` / `DASHBOARD_URL =
  https://briefbot.tailb058fe.ts.net`, `BBV2_DB_PATH`, `BBV2_LOG_DIR`.
- `/home/briefbot/briefbot/config/briefbot-v2-firebase-adminsdk-*.json` — Firebase
  Admin service account (backend token verification).
- `/home/briefbot/briefbot/dashboard/.env` — `VITE_FIREBASE_*` (web config) +
  `VITE_API_BASE=https://briefbot.tailb058fe.ts.net`. **Baked into the bundle at
  build time** → changing these requires a dashboard rebuild (the deploy does this).

## CI/CD — push to deploy

**Trigger:** push to `main` (or Actions → *deploy* → "Run workflow", or
`gh workflow run deploy.yml`). Defined in `.github/workflows/deploy.yml`.

**Why a self-hosted runner:** the VM is tailnet/NAT-only, so a cloud runner can't
reach it without a Tailscale auth key **and** an SSH deploy key stored as GitHub
secrets. A runner **on the VM** connects *outbound* to GitHub — no inbound, no
exposed ports, no CI secrets. (Safe because the repo is **private**; never run a
self-hosted runner on a public repo.)

**What the job does** (runs as `briefbot` on the VM):
1. `actions/checkout` the repo into the runner workspace.
2. `rsync -a --delete` the checkout → `/home/briefbot/briefbot`, **excluding**
   `.git .github .env data config .venv dist node_modules` so VM
   secrets/DB/venv survive untouched.
3. `pip install -r requirements.txt` (backend deps).
4. `npm install && npm run build` in `dashboard/` (rebuilds `dist/` against the
   VM's `dashboard/.env`).
5. `sudo systemctl restart bbv2`.
6. Health check `http://127.0.0.1:8080/health`.

**To ship a change:** edit locally → `git push`. ~30 s later it's live. Brief
(~seconds) backend blip during the restart.

## Operations runbook

SSH in: `ssh briefbot@10.0.0.224` (LAN) or `ssh briefbot@briefbot.tailb058fe.ts.net`
(tailnet). All commands run as `briefbot` (passwordless sudo).

```bash
# health / status
systemctl status bbv2 nginx
sudo tailscale serve status
curl -fsS http://127.0.0.1:8080/health

# logs
journalctl -u bbv2 -f                      # backend
sudo tail -f /var/log/nginx/error.log      # web
tail -f /home/briefbot/briefbot/data/logs/cron.log   # tick/nightly

# restart / manual deploy
sudo systemctl restart bbv2
gh workflow run deploy.yml                  # from the Mac (re-deploys main)

# rebuild dashboard by hand
cd /home/briefbot/briefbot/dashboard && npm run build && sudo systemctl restart bbv2

# run the pull / brief jobs by hand
cd /home/briefbot/briefbot && .venv/bin/python -m bbv2 tick
cd /home/briefbot/briefbot && .venv/bin/python -m bbv2 nightly --dry-run
```

**Add a family member:** invite them to the tailnet (Tailscale admin → invite) →
they install Tailscale → browse the URL. They self-register via Firebase login.

**Common issues**
- *Login fails / "unauthorized domain":* add the serving host to Firebase
  Authorized domains.
- *502 / blank page:* `bbv2` is down — `journalctl -u bbv2 -n 50`, then restart.
- *Deploy didn't run:* runner offline — `systemctl status
  actions.runner.migoVanDingo-briefbot.briefbot-vm`; check GitHub → Settings →
  Actions → Runners shows `briefbot-vm` idle/online.
- *Re-register the runner* (token expired / re-provision):
  `gh api -X POST repos/migoVanDingo/briefbot/actions/runners/registration-token`
  then `cd ~/actions-runner && ./config.sh --url … --token <T> --replace`.

## How it was provisioned (history / gotchas)

- VM created via the Proxmox MCP (`create_vm`); ISO/cloud-init done via the Proxmox
  REST API with the token.
- **Ubuntu cloud images would not boot** under SeaBIOS on the ZFS zvol → installed
  from the **desktop ISO** instead (normal installer, "Erase disk").
- `create_vm` needed **`SDN.Use`** on `/sdn` for the token (PVE 8 manages `vmbr0`
  under SDN) — granted via `PVESDNUser`.
- The Proxmox MCP `create_vm` is bare-bones (cpu/mem/disk only); ISO attach,
  cloud-init, boot order, resize were done via the REST API (`curl` + token).

## Not yet exposed

The **consumer API** (root `/topics` `/items` `/health`, service-token read used by
the `trader` project) is **not** proxied by nginx — those paths collide with the
dashboard's own SPA routes (only `/api/*` is proxied). When the trader↔bbv2
integration resumes, expose the consumer API on its own path/port (a second
`tailscale serve` path or a dedicated location block).
