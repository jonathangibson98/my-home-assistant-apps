ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:noarch
FROM ${BUILD_FROM}

# Install system dependencies if needed
RUN apk add --no-cache jq

# Copy requirements and install python packages
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt

# Copy root filesystem
COPY rootfs /

WORKDIR /
CMD [ "/run.sh" ]
