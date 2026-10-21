# Why this directory exists

Ubuntu's live-build (3.0~a57) still assumes syslinux 4 paths and the
`syslinux-themes-ubuntu-oneiric` / `gfxboot-theme-ubuntu` packages, none of
which exist in noble. This is live-build's own `isolinux` template
(`--syslinux-theme live-build`) with:

- `isolinux.bin` and the `.c32` modules pointed at noble's real paths
  (`/usr/lib/ISOLINUX`, `/usr/lib/syslinux/modules/bios`), including
  `ldlinux.c32`, `libcom32.c32`, `libutil.c32`, which syslinux 6 needs to boot;
- a pre-rendered `splash.png`, so the `rsvg` binary (renamed `rsvg-convert`
  in noble) is never invoked;
- an empty cpio `bootlogo`, because `lb_binary_syslinux` unconditionally
  unpacks and repacks that file even when gfxboot is not used.

`config/includes.chroot/usr/share/gfxboot-theme-ubuntu/bootlogo.tar.gz` is an
empty tarball for the same reason: ubuntu mode untars it unconditionally.
