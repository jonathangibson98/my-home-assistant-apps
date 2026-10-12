ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install code-server and utilities for handling folders/zips
RUN apk add --no-cache \
    nodejs \
    npm \
    git \
    bash \
    curl \
    unzip \
    jq

# Install code-server globally
RUN curl -fsSL https://code-server.dev/install.sh | sh

# Copy startup script
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8443

CMD [ "/run.sh" ]
