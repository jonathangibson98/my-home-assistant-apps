FROM alpine:3.24
RUN apk add --no-cache python3 py3-pip py3-aiohttp py3-cryptography py3-requests mitmproxy \
 && pip install --no-cache-dir --break-system-packages paho-mqtt tinytuya tuya-device-sharing-sdk segno
COPY run.py tuya_model.py tuya_cloud.py ci_capture.py index.html /
CMD ["python3", "/run.py"]
