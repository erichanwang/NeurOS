# NeurOS Docker Build Container
# Provides a consistent build environment for creating NeurOS ISOs.
#
# Usage:
#   docker build -t neuros-build .
#   docker run --privileged -v "$(pwd):/workspace" -w /workspace neuros-build ./build.sh
#
# Or use with docker-compose:
#   docker compose up

# Pinned to a digest instead of the floating 24.04 tag, which Canonical
# rebuilds in place for security updates -- the digest is immutable, so the
# build container's starting filesystem can't drift between builds.
FROM ubuntu:24.04@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    live-build \
    zstd \
    lz4 \
    xz-utils \
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

# Install Python dependencies (pinned so this doesn't silently pick up a
# newer requests on rebuild)
RUN pip3 install --break-system-packages requests==2.34.2 || true

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

# Upstream bug in Ubuntu's live-build 3.0~a57: the casper branch of
# lb_binary_syslinux rewrites ${_SUFFIX}/live.cfg (undefined) instead of
# ${_TARGET}/live.cfg, so any build with a plain live.cfg template dies with
# "sed: can't read /live.cfg". Fix the one variable name.
RUN sed -i 's|${_SUFFIX}/live.cfg|${_TARGET}/live.cfg|' /usr/lib/live/build/lb_binary_syslinux \
 && grep -q '${_TARGET}/live.cfg' /usr/lib/live/build/lb_binary_syslinux \
 && ! grep -q '_SUFFIX' /usr/lib/live/build/lb_binary_syslinux


# genisoimage (cdrkit) cannot store a file over 4 GiB; NeurOS's squashfs is
# ~8.5 GB because Mistral 7B ships inside it. Build the ISO with xorriso's
# mkisofs emulation at ISO level 3 instead, which is what Ubuntu's own ISOs use.
RUN sed -i \
      -e 's|Check_package chroot/usr/bin/genisoimage genisoimage|Check_package chroot/usr/bin/xorriso xorriso|' \
      -e 's|^genisoimage \${GENISOIMAGE_OPTIONS}|xorriso -as mkisofs -iso-level 3 ${GENISOIMAGE_OPTIONS}|' \
      /usr/lib/live/build/lb_binary_iso \
 && grep -q 'xorriso -as mkisofs -iso-level 3' /usr/lib/live/build/lb_binary_iso \
 && grep -q 'chroot/usr/bin/xorriso xorriso' /usr/lib/live/build/lb_binary_iso

CMD ["--help"]
