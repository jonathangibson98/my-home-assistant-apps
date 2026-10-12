ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install Node.js, git, bash, curl, unzip, and jq natively
RUN apk add --no-cache \
    nodejs \
    npm \
    git \
    bash \
    curl \
    unzip \
    jq

# Download code-server tarball directly
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then CODE_ARCH="arm64"; else CODE_ARCH="amd64"; fi && \
    curl -fL https://github.com/coder/code-server/releases/download/v4.22.1/code-server-4.22.1-linux-$CODE_ARCH.tar.gz | tar -xz -C /usr/local/lib && \
    mv /usr/local/lib/code-server-4.22.1-linux-$CODE_ARCH /usr/local/lib/code-server

# Force code-server to use the system node binary instead of looking for its own missing bundle wrapper
RUN rm -rf /usr/local/lib/code-server/lib/node && \
    ln -s /usr/bin/node /usr/local/lib/code-server/lib/node && \
    ln -s /usr/local/lib/code-server/bin/code-server /usr/bin/code-server

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8443

CMD [ "/run.sh" ]
