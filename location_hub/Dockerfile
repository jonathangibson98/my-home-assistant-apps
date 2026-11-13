ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24
FROM $BUILD_FROM

# Python + aiohttp straight from Alpine (no compiling on a Pi). paho-mqtt 2.x from pip, because the
# Location Hub half uses the version-2 callback API.
RUN apk add --no-cache python3 py3-aiohttp py3-pip tzdata \
 && pip3 install --no-cache-dir --break-system-packages "paho-mqtt>=2,<3"

ARG BUILD_VERSION=
ENV MT_VERSION=$BUILD_VERSION

WORKDIR /data

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8099/health"]

CMD [ "/run.sh" ]
