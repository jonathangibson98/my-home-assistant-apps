ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM
RUN apk add --no-cache python3 py3-aiohttp tzdata
COPY run.sh /run.sh
COPY main.py /app/main.py
COPY index.html /app/www/index.html
RUN chmod a+x /run.sh
CMD ["/run.sh"]
