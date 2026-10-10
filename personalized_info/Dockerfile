FROM alpine:3.22
RUN apk add --no-cache python3 py3-pip py3-aiohttp py3-yaml \
 && pip install --no-cache-dir --break-system-packages paho-mqtt
COPY run.py index.html /
CMD ["python3", "/run.py"]
