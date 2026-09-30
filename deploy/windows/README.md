# Windows

There is no native Windows installer yet. Two supported routes:

## Docker Desktop (recommended)

```powershell
cd deploy\compose
copy ..\..\.env.example .env      # set SEARXNG_SECRET (any long random string)
docker compose up -d --build
```

Open http://127.0.0.1:8787 and follow the setup guide. Your data lives in the `gleanwise-data` Docker volume.
Stop with `docker compose down` (add `-v` to also delete your data).

## WSL 2

Inside an Ubuntu WSL 2 distribution with systemd enabled (`/etc/wsl.conf` → `[boot] systemd=true`):

```bash
./deploy/install.sh
```

Then browse to http://127.0.0.1:8787 from Windows.

A signed installer that hides this behind a normal setup wizard is planned but not built.
