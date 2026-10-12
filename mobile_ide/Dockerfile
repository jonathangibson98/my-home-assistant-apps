ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install File Browser, Samba, and utilities
RUN apk add --no-cache \
    filebrowser \
    samba \
    samba-common-tools \
    bash \
    jq

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8080 445 139

CMD [ "/run.sh" ]
