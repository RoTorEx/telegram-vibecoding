#!/bin/sh
set -eu
umask 077
python -c 'import uuid; print(uuid.uuid4().hex)' > /tmp/telegram-vibecoding-instance
exec /app/.venv/bin/telegram-vibecoding "$@"
