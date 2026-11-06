ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip build-base libffi-dev openssl-dev

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py run.sh ./
RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
