# Deploying OppTrack on the RTX Blackwell machine

Manual runbook -- run every command below yourself, on that machine, over
SSH. Nothing here executes remotely on your behalf.

What this gets you: the full stack (Postgres, Redis, MinIO, the API, the
scheduler, the SPA, and a local vLLM model server using the machine's GPU)
behind Caddy on 80/443 with real HTTPS and no manual certificate work, plus
an optional second copy of the UI on GitHub Pages talking to the same
backend.

## 0. Before you start

You'll need, on the RTX machine:

- Docker Engine + the Compose plugin (`docker compose version` should print
  something; if it only has `docker-compose` with a hyphen, that's the old
  standalone binary -- fine too, just swap the command).
- The [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  so containers can see the GPU (`nvidia-smi` should work; `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` should also work once the toolkit's installed).
- Its public IP, reachable on ports 80 and 443 from the internet (check your
  cloud/hosting provider's firewall or security group, not just the OS
  firewall -- both have to allow it).
- A Hugging Face account with the Llama 3.3 license accepted, and an access
  token, if you're running the local model (see step 3). Skip this if you'd
  rather point JUDGMENT_BACKEND at the Anthropic API instead.

## 1. Get the code onto the machine

This project isn't pushed to a git remote yet. Until it is, copy it over
directly -- from your own machine, not the RTX box:

```bash
# from wherever this repo lives locally
rsync -avz --exclude node_modules --exclude __pycache__ --exclude '*.db' \
  ./opportunity_tracking_agent/ you@RTX-PUBLIC-IP:~/opportunity_tracking_agent/
```

(Or `scp -r`, or a USB stick -- whatever's easiest. If you later put this in
a GitHub repo, `git clone` replaces this step and `git pull` handles
updates -- see step 6.)

SSH in for everything from here on:

```bash
ssh you@RTX-PUBLIC-IP
cd opportunity_tracking_agent/deliverables
```

## 2. Pick a hostname

You said no domain yet, so use a **nip.io hostname** -- it needs no signup
and resolves straight to your IP, which lets Caddy get you a real,
browser-trusted Let's Encrypt certificate (this matters for step 7: GitHub
Pages will refuse to talk to a backend with an untrusted cert).

Take your public IP and replace the dots with dashes, then append
`.nip.io`. `203.0.113.45` becomes `203-0-113-45.nip.io`. That's it --
`https://203-0-113-45.nip.io` will resolve and work with no further setup.
(Confirm your actual public IP first with `curl -4 ifconfig.me` run on the
RTX box itself, not your laptop.)

Got a real domain instead, or get one later? Point its A record at the
public IP and use that hostname everywhere below instead of the nip.io one
-- nothing else changes.

## 3. Configure the environment

```bash
cp deploy/.env.production.example deploy/.env.production
```

Edit `deploy/.env.production` (never commit this file -- it's gitignored):

- `OPPTRACK_DOMAIN` -- the nip.io hostname (or real domain) from step 2.
- `CORS_ORIGINS` -- `https://<that hostname>` at minimum; add
  `https://<your-github-username>.github.io` too if you're doing step 7.
- `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD` -- anything but the defaults.
- `HUGGING_FACE_HUB_TOKEN` -- needed to download Llama 3.3 weights the first
  time the `vllm` container starts. Get one at
  huggingface.co/settings/tokens and accept the model's license on its
  model page first, or the download will 403.
- `OTP_DELIVERY=console` is fine to start with -- it puts your own sign-in
  code in `docker compose logs backend` (you have SSH access). Switch to
  `smtp` and fill in the `SMTP_*` vars once other people need to sign in and
  can't tail your logs to get their code.
- Leave `JUDGMENT_MODE=mock` for now -- flip to `live` in step 5, once
  you've confirmed the stack is actually up.

## 4. Open the firewall

Only 22 (SSH) and 80/443 need to reach the internet. Everything else
(Postgres, Redis, MinIO, the backend, the frontend's own nginx) already
binds to `127.0.0.1` only in `docker-compose.yml`, so it's not reachable
from outside even without a firewall rule -- but belt and suspenders:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable   # if it wasn't already
sudo ufw status
```

## 5. Bring the stack up

From `deliverables/`:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  --env-file deploy/.env.production --profile local-model up -d --build
```

First run pulls/builds everything and the `vllm` container downloads the
model weights (tens of GB -- can take a while depending on the link).
Watch it:

```bash
docker compose --env-file deploy/.env.production logs -f vllm backend edge
```

Once `vllm` logs show it's serving and `edge` shows it obtained a
certificate, check from your own laptop (not the RTX box, so you're testing
the real public path):

```bash
curl -s https://203-0-113-45.nip.io/health
# {"status":"ok"}
curl -s https://203-0-113-45.nip.io/api/v1/dev/tables
# should 404 -- confirms DEV_TOOLS_ENABLED=false took effect
```

If `edge` can't get a certificate, it's almost always port 80 not actually
reachable from the internet (check the cloud provider's security group
again) or `OPPTRACK_DOMAIN` not matching what you tested against.

Now flip judgment on for real: set `JUDGMENT_MODE=live` in
`deploy/.env.production` and recreate just the two services that read it:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  --env-file deploy/.env.production up -d backend scheduler
```

## 6. Create the first admin

`docker-compose.prod.yml` sets `AUTH_MODE=local` (real email + password +
one-time code), which has no self-service way to become the first admin --
see `scripts/bootstrap_admin.py`'s docstring for why. Run it once, inside
the running backend container:

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  --env-file deploy/.env.production exec backend \
  python -m scripts.bootstrap_admin --email you@example.com --name "Your Name" --password 'pick a real password'
```

Sign in at `https://203-0-113-45.nip.io/` with that email and password.
From there, use the Users screen to provision everyone else -- they sign up
with their own password at the same URL; their role only takes effect once
you've added their email as a user there (no self-registration grants
access on its own).

Do **not** run `scripts/seed_demo_accounts.py` here -- it creates five
accounts with a password that's printed in this repo's source
(`OppTrack-2026!`), fine for a laptop, not fine on a public IP.

## 7. Optional: also serve the UI from GitHub Pages

Skip this if the RTX machine serving everything (what you just set up) is
enough -- it's simpler to operate and is already CORS-free. Do this if you
specifically want the UI reachable at a `github.io` URL too.

1. Push this repo to GitHub (repo root is `opportunity_tracking_agent/` --
   confirm `.github/workflows/` sits directly under it, not under
   `deliverables/`). **Before you push**, decide whether
   `opportunity_tracking_agent/data/TrackF (1).xlsx` and anything else
   under `docs/` contains real customer or pricing data you don't want in a
   GitHub repo (especially a public one) -- add it to a root `.gitignore`
   if so. `deliverables/.gitignore` already keeps `.env`, `*.db` and `logs/`
   out, but it only covers paths inside `deliverables/`.
2. Repo Settings -> Pages -> Source: **GitHub Actions**.
3. Repo Settings -> Secrets and variables -> Actions -> Variables -> New
   repository variable: `VITE_API_BASE` = `https://203-0-113-45.nip.io/api/v1`
   (your real hostname from step 2).
4. Make sure `CORS_ORIGINS` in `deploy/.env.production` includes
   `https://<your-github-username>.github.io`, then
   `docker compose ... up -d backend` to pick it up.
5. Push to `main` (or run the `deploy-pages` workflow manually from the
   Actions tab). It builds `deliverables/frontend` against that API base
   and deploys to Pages.

Because the nip.io hostname has a real Let's Encrypt certificate (step 2),
this works with no browser cert warning -- that's the main reason to use
nip.io over a bare-IP/self-signed setup when Pages is in the picture.

## 8. Using the Dev Portal against this deployment

The in-app "Dev Portal" (admin-only screen; DB table browser, log tail) is
backed by `DEV_TOOLS_ENABLED=false` here on purpose -- its API has no auth
check of its own, so it must not be reachable from the public IP. To use it
against production data anyway, from your laptop:

```bash
ssh -L 8000:127.0.0.1:8000 you@RTX-PUBLIC-IP
```

then temporarily flip it on, use it, and flip it back off:

```bash
# on the RTX box
sed -i 's/DEV_TOOLS_ENABLED=false/DEV_TOOLS_ENABLED=true/' deploy/docker-compose.prod.yml   # or export it inline
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d backend
# ... use it at http://localhost:8000/api/v1/dev/tables via the tunnel ...
git checkout -- deploy/docker-compose.prod.yml   # or set it back to false
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d backend
```

## 9. Updating later

```bash
cd opportunity_tracking_agent/deliverables
git pull   # or re-rsync, if you're not on git yet
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  --env-file deploy/.env.production --profile local-model up -d --build
```

Migrations run automatically on backend container start
(`backend/Dockerfile`'s `alembic upgrade head` before `uvicorn`).

## 10. Backups

`backend/scripts/backup.py` exists for this. Run it on a cron on the RTX
box against the `postgres`/`minio` volumes; where to put the output (off
that machine, ideally) is up to you -- this repo doesn't do off-box backup
transport for you.

## Checklist before calling this "live"

- [ ] `curl https://<host>/health` from a machine that isn't the RTX box
- [ ] `curl https://<host>/api/v1/dev/tables` returns 404
- [ ] Signed in as the bootstrapped admin, provisioned at least one more
      real person from the Users screen
- [ ] `OTP_DELIVERY` is `smtp`, not `console`, before anyone but you needs
      to sign in
- [ ] `deploy/.env.production` is **not** committed to git
      (`git status` shouldn't show it -- it's gitignored, but double-check
      if you ever restructure `.gitignore`)
- [ ] A plan for step 10 (backups) beyond "the volume exists on one disk"
