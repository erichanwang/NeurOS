#!/usr/bin/env bash
# Headless boot check for the ISO: boots it under QEMU/KVM with no display,
# screenshots the console every 30 s via QMP, and fails if the screen never
# changes from the first frame (i.e. nothing past the boot menu happened).
# The PNGs land in the output dir so a human can confirm what booted.
#
#   scripts/boot-test.sh [iso] [outdir]       WAIT=seconds (default 180)
set -euo pipefail
ISO="${1:-live-image-amd64.hybrid.iso}"
OUT="$(realpath -m "${2:-boot-test}")"   # absolute: -daemonize chdirs QEMU to /
WAIT="${WAIT:-180}"
MEM="${MEM:-6144}"
[[ -f "$ISO" ]] || { echo "no ISO at $ISO" >&2; exit 2; }
mkdir -p "$OUT"; rm -f "$OUT"/*.ppm "$OUT"/*.png "$OUT"/qmp.sock "$OUT"/qemu.pid
KVM=(); [[ -w /dev/kvm ]] && KVM=(-enable-kvm -cpu host)
qemu-system-x86_64 "${KVM[@]}" -m "$MEM" -smp 4 -cdrom "$ISO" -boot d -vga virtio \
  -display none -qmp unix:"$OUT/qmp.sock",server,nowait -pidfile "$OUT/qemu.pid" -daemonize
trap 'kill "$(cat "$OUT/qemu.pid" 2>/dev/null)" 2>/dev/null || true' EXIT

shot() {  # shot NAME -> writes NAME.png, prints mean brightness 0-255
python3 - "$OUT" "$1" <<'PY'
import json, socket, sys, time
from PIL import Image, ImageStat
out, name = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX); s.connect(f"{out}/qmp.sock"); f = s.makefile("rw")
def rpc(c): f.write(json.dumps(c) + "\n"); f.flush(); return json.loads(f.readline())
json.loads(f.readline())                      # greeting
rpc({"execute": "qmp_capabilities"})
r = rpc({"execute": "screendump", "arguments": {"filename": f"{out}/{name}.ppm"}})
if "error" in r: sys.exit(f"screendump failed: {r['error']}")
time.sleep(0.5)
im = Image.open(f"{out}/{name}.ppm").convert("L"); im.save(f"{out}/{name}.png")
print(int(ImageStat.Stat(im).mean[0]))
PY
}

sleep 15; first=$(shot t015); echo "t=15s  brightness=$first"
last="$first"; t=15
while (( t < WAIT )); do
  sleep 30; t=$((t + 30)); last=$(shot "t$(printf %03d "$t")"); echo "t=${t}s brightness=$last"
done
if cmp -s "$OUT/t015.ppm" "$OUT/t$(printf %03d "$t").ppm"; then
  echo "FAIL: console never changed after the first frame"; exit 1
fi
echo "OK: console changed between t=15s and t=${t}s; inspect $OUT/*.png"
