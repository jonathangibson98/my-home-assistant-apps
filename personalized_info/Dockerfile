FROM alpine:3.24
RUN apk add --no-cache python3 py3-pip py3-aiohttp py3-yaml \
 && pip install --no-cache-dir --break-system-packages paho-mqtt
COPY run.py extra_links.py extra_links.js profile_data.py index.html /
CMD ["python3", "/run.py"]
