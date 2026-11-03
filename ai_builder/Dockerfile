ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip py3-aiohttp py3-yaml py3-pillow \
 && pip install --no-cache-dir --break-system-packages vtracer

WORKDIR /app
COPY main.py svg_tool.py /app/
COPY www /app/www
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
