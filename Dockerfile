# NeurOS Docker Build Container
# Provides a consistent build environment for creating NeurOS ISOs.
#
# Usage:
#   docker build -t neuros-build .
#   docker run --privileged -v "$(pwd):/workspace" -w /workspace neuros-build ./build.sh
#
# Or use with docker-compose:
#   docker compose up

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    live-build \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux \
    grub-pc-bin \
    grub-efi-amd64-bin \
    mtools \
    dosfstools \
    wget \
    curl \
    ca-certificates \
    gnupg \
    python3 \
    python3-pip \
    python3-venv \
    git \
    rsync \
    jq \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create workspace
WORKDIR /workspace
VOLUME /workspace

# Copy NeurOS config files into the container
COPY config/ /opt/neuros/config/
COPY build.sh /opt/neuros/
COPY Makefile /opt/neuros/
COPY validate-build.sh /opt/neuros/

# Install Python dependencies
RUN pip3 install --break-system-packages requests || true

# Set up neuros tools in container
RUN mkdir -p /usr/local/bin && \
    for f in /opt/neuros/config/includes.chroot/usr/local/bin/*; do \
      [ -f "$f" ] && cp "$f" "/usr/local/bin/$(basename "$f")" 2>/dev/null || true; \
    done && \
    chmod +x /usr/local/bin/nn /usr/local/bin/neuros-* 2>/dev/null || true

# Verify installation
RUN echo "NeurOS Build Container Ready" && \
    echo "Python: $(python3 --version)" && \
    echo "Live-build: $(lb --version 2>&1 || echo 'installed')" && \
    echo "Tools: $(ls /usr/local/bin/ | grep neuros | tr '\n' ' ')"

ENTRYPOINT ["/opt/neuros/build.sh"]
CMD ["--help"]
