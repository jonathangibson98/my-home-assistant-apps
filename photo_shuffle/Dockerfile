ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pillow py3-paho-mqtt

COPY run.sh /run.sh
COPY main.py /app/main.py
RUN chmod a+x /run.sh

CMD ["/run.sh"]
