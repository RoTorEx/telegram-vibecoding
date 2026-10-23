FROM python:3.13-slim-bookworm
ARG APP_UID=1002
ARG APP_GID=1002
ARG APP_HOME=/home/alex
ARG REVISION=development
RUN groupadd --gid "$APP_GID" developer && useradd --uid "$APP_UID" --gid "$APP_GID" \
    --home-dir "$APP_HOME" --create-home developer
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir uv==0.10.9 && uv sync --frozen --no-dev --no-editable
COPY scripts/entrypoint.sh /usr/local/bin/telegram-vibecoding-entrypoint
RUN chmod 755 /usr/local/bin/telegram-vibecoding-entrypoint
ENV TELEGRAM_VIBECODING_REVISION=$REVISION
ENV PATH="/app/.venv/bin:$PATH"
USER developer
ENTRYPOINT ["/usr/local/bin/telegram-vibecoding-entrypoint"]
