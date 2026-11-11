FROM python:3.12-slim AS builder

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /app

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-ansi


FROM python:3.12-slim

ARG LOCAL_UID=1000
ARG LOCAL_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --gid "${LOCAL_GID}" nekobot \
    && useradd --create-home --uid "${LOCAL_UID}" --gid "${LOCAL_GID}" nekobot \
    && mkdir -p /app/data \
    && chown nekobot:nekobot /app/data

COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml bot.py ./
COPY plugins ./plugins
COPY persona ./persona
COPY stickers ./stickers

USER nekobot

EXPOSE 8080

CMD ["python", "bot.py"]
