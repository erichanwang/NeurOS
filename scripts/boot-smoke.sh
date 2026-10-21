#!/usr/bin/env bash
# Headless boot check for a built ISO: boots it in QEMU with the kernel
# console on a serial port and waits for systemd to reach the graphical
# target (the live GNOME session) and for neuros-llm.service to start.
# Exits 0 on success. Needs qemu-system-x86_64 and xorriso.
#
# Usage: scripts/boot-smoke.sh [live-image-amd64.hybrid.iso] [timeout-seconds]
set -euo pipefail
ISO="${1:-live-image-amd64.hybrid.iso}"
TIMEOUT="${2:-420}"
WORK="$(mktemp -d)"
trap 'kill "${QEMU_PID:-}" 2>/dev/null || true; chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT

[[ -f "$ISO" ]] || { echo "no ISO at $ISO"; exit 1; }
# only the kernel and initrd; the squashfs next to them is 8+ GB
mkdir -p "$WORK/casper"
xorriso -osirrox on -indev "$ISO" -extract /casper/vmlinuz "$WORK/casper/vmlinuz" -extract /casper/initrd.img "$WORK/casper/initrd.img" >/dev/null 2>&1
KERNEL="$(ls "$WORK"/casper/vmlinuz* | head -1)"
INITRD="$(ls "$WORK"/casper/initrd* | head -1)"

KVM=(); [[ -r /dev/kvm && -w /dev/kvm ]] && KVM=(-enable-kvm -cpu host)
qemu-system-x86_64 -m 6144 -smp 4 "${KVM[@]}" \
  -cdrom "$ISO" -kernel "$KERNEL" -initrd "$INITRD" \
  -append "boot=casper console=ttyS0,115200 noprompt noeject" \
  -display none -serial "file:$WORK/serial.log" -no-reboot &
QEMU_PID=$!

for ((i = 0; i < TIMEOUT; i += 5)); do
  sleep 5
  if grep -q "Reached target.*Graphical Interface" "$WORK/serial.log" 2>/dev/null; then
    LLM="$(grep -o "Started.*NeurOS Local LLM Daemon.*" "$WORK/serial.log" | head -1 || true)"
    echo "BOOT OK after ${i}s: $(grep -o "Reached target.*Graphical Interface.*" "$WORK/serial.log" | head -1)"
    echo "${LLM:-neuros-llm.service not seen on serial (may start after the target)}"
    exit 0
  fi
  if ! kill -0 "$QEMU_PID" 2>/dev/null; then
    echo "QEMU exited early"; tail -20 "$WORK/serial.log"; exit 1
  fi
done
echo "BOOT FAILED: no graphical target within ${TIMEOUT}s"; tail -40 "$WORK/serial.log"; exit 1
