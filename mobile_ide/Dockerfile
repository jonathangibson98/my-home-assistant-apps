ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install dependencies, build tools, python, and utilities
RUN apk add --no-cache \
    nodejs \
    npm \
    git \
    bash \
    curl \
    unzip \
    jq \
    python3 \
    make \
    g++

# Install code-server globally with Node version override
RUN export FORCE_NODE_VERSION=20 && curl -fsSL https://code-server.dev/install.sh | sh

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8443

CMD [ "/run.sh" ]
