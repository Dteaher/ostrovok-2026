FROM python:3.11.14-slim-bookworm AS builder
WORKDIR /build
COPY requirements.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11.14-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_PORT=8080
WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels \
    && groupadd --gid 10001 oplan \
    && useradd --uid 10001 --gid oplan --no-create-home --shell /usr/sbin/nologin oplan \
    && mkdir -p /app/data \
    && chown -R oplan:oplan /app
COPY --chown=oplan:oplan app ./app
COPY --chown=oplan:oplan static ./static
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
