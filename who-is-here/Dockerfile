ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-aiohttp py3-paho-mqtt

COPY run.sh /run.sh
COPY main.py index.html /app/
RUN chmod a+x /run.sh

CMD ["/run.sh"]
