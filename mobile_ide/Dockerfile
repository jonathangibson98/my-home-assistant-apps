
ARG BUILD_FROM=ghcr.io/hassio-addons/base/aarch64:15.0.0
FROM ${BUILD_FROM}

# Install basic tools and native build dependencies
RUN apk add --no-cache \
    git \
    bash \
    curl \
    unzip \
    jq \
    python3 \
    alpine-sdk \
    pkgconf \
    libstdc++ \
    libc6-compat \
    krb5-dev

# Install Node.js 24 and npm from the official Node.js binaries
RUN ARCH="$(apk --print-arch)" && \
    case "$ARCH" in \
      aarch64) NODE_ARCH="arm64" ;; \
      x86_64) NODE_ARCH="x64" ;; \
      *) echo "Unsupported architecture: $ARCH"; exit 1 ;; \
    esac && \
    curl -fsSL "https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt" \
      -o /tmp/node-shasums.txt && \
    NODE_VERSION="$(grep -m1 -E '^node-v24\.[0-9]+\.[0-9]+-linux-' /tmp/node-shasums.txt \
      | sed -E 's/^node-(v24\.[0-9]+\.[0-9]+)-.*/\1/')" && \
    curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      -o /tmp/node.tar.xz && \
    grep "node-${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz$" /tmp/node-shasums.txt \
      | sha256sum -c - && \
    mkdir -p /usr/local/lib/nodejs && \
    tar -xJf /tmp/node.tar.xz -C /usr/local/lib/nodejs && \
    ln -sf "/usr/local/lib/nodejs/node-${NODE_VERSION}-linux-${NODE_ARCH}/bin/node" /usr/local/bin/node && \
    ln -sf "/usr/local/lib/nodejs/node-${NODE_VERSION}-linux-${NODE_ARCH}/bin/npm" /usr/local/bin/npm && \
    ln -sf "/usr/local/lib/nodejs/node-${NODE_VERSION}-linux-${NODE_ARCH}/bin/npx" /usr/local/bin/npx && \
    rm -f /tmp/node.tar.xz /tmp/node-shasums.txt

ENV PATH="/usr/local/bin:/usr/bin:/bin"

# Verify the actual runtime before installing code-server
RUN node --version && npm --version && \
    test "$(node -p 'process.versions.node.split(".")[0]')" = "24"

# Install code-server without a version override
RUN npm install --global code-server@4.141.0

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8443
CMD ["/run.sh"]
