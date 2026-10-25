# Running it for a real shop

Every option below starts the same way: the first person to open the app creates the
**owner** account, and the owner adds everyone else on **Settings → Users**.

| Role | Can |
|---|---|
| Staff | Record sales, receive deliveries, count stock, log waste, view the menu (with allergens) and the schedule |
| Manager | Everything day to day: menu, ingredients, ordering, schedule, sales imports, Excel |
| Owner | Also users, business settings and backups |

Staff never see other people's pay rates or contact details.

## Option A: one computer in the shop, tablets on the shop Wi-Fi

Good for a single location, with no monthly cost.

1. Install Python 3.9+ on the shop computer and download this project (see the README).
2. Start it so other devices can reach it:
   ```bash
   python -m app.server --host 0.0.0.0          # or: ./start.sh --host 0.0.0.0
   ```
   To start with your own menu instead of the sample juice bar, add `--empty` on the first run.
3. Find the computer's address on the network (Windows: `ipconfig`; Mac: System Settings → Wi-Fi → Details),
   for example `192.168.1.20`. On a tablet or phone on the same Wi-Fi, open `http://192.168.1.20:8000`.
4. Give the computer a fixed address in the router settings so the link keeps working, and set it to
   start the app when it boots.

Things to know:
- The connection is plain HTTP inside the shop network. Use a password-protected Wi-Fi network that customers
  are **not** on (not the guest network).
- The app only works while that computer is on.
- Back up regularly (see below): if the computer dies, the data goes with it.

## Option B: a small cloud server with HTTPS (recommended for anything beyond one counter)

Works from anywhere (home, a second location, a phone on mobile data), always over HTTPS.

You need a small Linux server (1 CPU and 1 GB of memory is plenty) with Docker installed, and a domain name.

1. Point a DNS name such as `inventory.yourshop.com` at the server's IP address.
2. Copy this project to the server and put your domain in `deploy/Caddyfile`.
3. From the project folder run:
   ```bash
   docker compose -f deploy/docker-compose.yml up -d --build
   ```
   Caddy obtains and renews the HTTPS certificate automatically.
4. Open `https://inventory.yourshop.com` and create the owner account straight away.

Hosted installs start with an empty catalog (no sample data). All data lives in the `menu-data` Docker volume.

### Many shops on one server

If you host shops for customers, use `deploy/multi/` instead: one server and one domain, with a demo shop at
`demo.yourbrand.com` and each customer at their own subdomain, each with separate data, users and backups.
`deploy/multi/reset-demo.sh` puts the demo back to the sample data (run it nightly from cron). On every new copy,
create the owner account straight away from the command line (`docker compose exec <shop> python -m app.auth add <name> owner`)
so nobody else can claim it. See `docs/launch/Launch-Plan.pdf`, sections 2 and 4.

## Option C: a hosting platform with a persistent disk

Any platform that can run a Dockerfile and attach a persistent disk works. Point it at this repository's
`Dockerfile`, attach the disk at `/data`, and set:

| Setting | Value | Why |
|---|---|---|
| `MENU_DATA_DIR` | `/data` (already set in the Dockerfile) | Where data, backups and the Excel export are kept |
| `MENU_SECURE_COOKIES` | `1` | The platform serves HTTPS, so cookies should be HTTPS-only |
| `MENU_TRUST_PROXY` | `1` | Use the visitor address the platform passes on, for login rate limits |
| `PORT` | whatever the platform requires | The app listens on it |

Without a persistent disk, everything is lost whenever the platform restarts the app.

## Backups

- The app copies all data to `data/backups/` after every change (one file per day, last 30 days),
  plus an extra copy before every Excel or sales import.
- Those copies sit on the same machine, so also **download a full backup** (data, users and pictures)
  from Settings → Backups at least weekly and keep it somewhere else (a USB drive, cloud storage).
  From the command line: `python -m app.backup zip`.
- To restore: stop the app, run `python -m app.backup restore menu-inventory-backup-YYYY-MM-DD.zip`,
  then start it again. The data being replaced is saved to `data/backups/` first.

## Accounts from the command line

```bash
python -m app.auth list                     # users and roles
python -m app.auth add jordan manager       # prompts for a password
python -m app.auth password pat             # reset a password (also re-enables the account)
```
With Docker: `docker compose -f deploy/docker-compose.yml exec app python -m app.auth password pat`.

## Security checklist

- [ ] Owner account created right after the first start, with a strong password
- [ ] Everyone has their own login (no shared accounts), with the lowest role that does the job
- [ ] Hosted: served over HTTPS only (Options B and C)
- [ ] In-shop: a private Wi-Fi network, not the customer network
- [ ] Weekly full backup stored off the machine
- [ ] Former employees disabled on Settings → Users the day they leave

Five wrong passwords for an account lock further tries from that address for five minutes. Sessions last
12 hours from the last activity; restarting the app signs everyone out.
