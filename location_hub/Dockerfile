ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM $BUILD_FROM
RUN apk add --no-cache python3 py3-aiohttp py3-pip tzdata \
 && pip3 install --no-cache-dir --break-system-packages "paho-mqtt>=2,<3"
WORKDIR /app
COPY run.sh /run.sh
COPY main.py tracker.py alerts.py /app/
COPY www/index.html /app/www/index.html
RUN chmod a+x /run.sh
CMD ["/run.sh"]
