ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install Samba and basic tools
RUN apk add --no-cache \
    samba \
    samba-common-tools \
    bash \
    curl \
    jq

# Download and install the official File Browser binary directly
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then FB_ARCH="arm64"; else FB_ARCH="amd64"; fi && \
    curl -fsSL https://github.com/filebrowser/filebrowser/releases/latest/download/linux-$FB_ARCH-filebrowser.tar.gz | tar -xz -C /usr/local/bin filebrowser

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080 445 139

CMD [ "/run.sh" ]
