FROM alpine:3.19

RUN apk add --no-cache python3 py3-aiohttp py3-pip
RUN pip3 install --no-cache-dir --break-system-packages "paho-mqtt>=2,<3"

COPY run.py /run.py

CMD ["python3", "/run.py"]
