ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install dependencies, build tools, python, and create python symlink
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
    g++ \
    && ln -s /usr/bin/python3 /usr/bin/python

# Install code-server globally with Node v20 override and explicit python config
RUN export FORCE_NODE_VERSION=20 && \
    npm config set python /usr/bin/python3 && \
    curl -fsSL https://code-server.dev/install.sh | sh

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8443

CMD [ "/run.sh" ]
