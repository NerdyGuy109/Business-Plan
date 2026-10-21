#!/usr/bin/env sh
# Start the menu & inventory website, then open http://localhost:8000
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
python3 -m app.server "$@"
