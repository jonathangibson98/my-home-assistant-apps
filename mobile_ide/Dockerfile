ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Samba + nginx (ingress proxy) + basic tools
RUN apk add --no-cache \
    samba \
    samba-common-tools \
    nginx \
    bash \
    curl \
    jq

# Official File Browser binary
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then FB_ARCH="arm64"; else FB_ARCH="amd64"; fi && \
    curl -fsSL "https://github.com/filebrowser/filebrowser/releases/latest/download/linux-${FB_ARCH}-filebrowser.tar.gz" \
      | tar -xz -C /usr/local/bin filebrowser && \
    chmod +x /usr/local/bin/filebrowser

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080 445 139

CMD [ "/run.sh" ]
