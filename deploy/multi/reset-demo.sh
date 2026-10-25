#!/usr/bin/env sh
# Put the demo shop back to the sample juice bar. Demo users and passwords are kept.
# Run it before a demo, or nightly from cron:
#   15 3 * * *  /path/to/deploy/multi/reset-demo.sh >> /var/log/menu-demo-reset.log 2>&1
set -e
cd "$(dirname "$0")"
docker compose stop demo
docker compose run --rm --no-deps demo python -m app.seed
docker compose start demo
echo "$(date) demo reset"
