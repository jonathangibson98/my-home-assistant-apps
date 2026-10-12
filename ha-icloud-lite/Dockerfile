ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}

# Install Python and jq so we can read configuration settings
RUN \
    apk add --no-cache \
        python3 \
        py3-pip \
        jq

# Copy all your source files into the container
COPY . /app
WORKDIR /app

# Set up the startup script
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
