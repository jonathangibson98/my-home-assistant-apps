ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pillow py3-paho-mqtt py3-flask py3-requests

WORKDIR /app
COPY run.sh /run.sh
COPY main.py index.html /app/
RUN chmod a+x /run.sh

CMD ["/run.sh"]
