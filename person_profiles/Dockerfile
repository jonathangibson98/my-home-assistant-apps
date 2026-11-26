ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-aiohttp

COPY main.py profile_data.py index.html run.sh /app/
RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
