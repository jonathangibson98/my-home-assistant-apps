ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install required runtime utilities
RUN apk add --no-cache \
    curl \
    bash \
    git \
    unzip \
    jq

# Install official prebuilt code-server binary directly
RUN curl -fsSL https://code-server.dev/install.sh | sh

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8443

CMD [ "/run.sh" ]
