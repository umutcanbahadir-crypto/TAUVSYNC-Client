# TAUVSYNC for Ubuntu 22.04 LTS (amd64)

This is a **native Linux build**, produced from the same v2.2.1 Python client as
Windows, on GitHub's `ubuntu-22.04` x86_64 runner. It does not run the Windows
EXE under Wine. It is a beta and requires a graphical GNOME/X11/XWayland
desktop session; headless/SSH servers are not supported as desktop clients.

## Recommended: Debian installer

Download `tauvsync_2.2.1_amd64.deb` and the matching `.sha256` from the
[v2.2.1 release](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/tag/v2.2.1).
Verify the checksum in the directory containing both downloads:

```bash
sha256sum -c tauvsync_2.2.1_amd64.deb.sha256
sudo apt install ./tauvsync_2.2.1_amd64.deb
tauvsync
```

The package installs `/usr/bin/tauvsync`, its desktop-menu launcher, and the
TAUV icon. No standalone Python installation is needed. The app opens without
KiCad for project browsing; **KiCad 10 is required to edit projects**.

## Install KiCad 10

Ubuntu 22.04's stock KiCad is too old for this client. The upstream official
KiCad 10 PPA supports Ubuntu:

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository --yes ppa:kicad/kicad-10.0-releases
sudo apt update
apt-cache policy kicad
sudo apt install --install-recommends kicad
kicad --version
```

Ensure the reported KiCad version is **10.x**. TAUVSYNC deliberately checks
the version and refuses to launch an older KiCad via a misleading file
association. If KiCad 10 is installed outside the PATH, launch TAUVSYNC with
`TAUV_KICAD10_EXE=/absolute/path/to/kicad tauvsync`.

## Portable alternative

The release also includes `TAUVSYNC-linux-x86_64-2.2.1.tar.gz`. Install
`libsecret-tools` and `xdg-utils` if needed, extract the archive and run
`./TAUVSYNC` from its directory. Prefer the Debian package for dependencies
and desktop-menu integration.

## Credential security

The optional **Remember login** setting uses the Linux desktop Secret Service
via `secret-tool`, typically backed by GNOME Keyring. The password is never
stored as plaintext in the local TAUV preferences. On desktops without an
unlocked keyring, remembering credentials is unavailable but manual login and
normal synchronization continue. On Windows, existing DPAPI behavior is
unchanged.

## Collaboration and updates

- Project sync, previews, download/upload, immutable revision history,
  exclusive project locks, and recovery behavior use the existing server API.
- **Open Folder** opens the managed local project in the Linux file manager
  via `xdg-open` (no download, permission change or edit lock is implied).
- Startup update checks use the public GitHub Releases feed and offer the
  official release page; TAUVSYNC does not silently replace binaries.
- Keep the application running/minimized while editing. Close KiCad editors
  before releasing a project lock.
- Linux and Windows builds use the same server account and project permissions.

**Server requirement:** The v2.2.1 client needs the newer TAUVSYNC backend
providing `/api/tauvsync/projects/{id}/edit-lock`. Installing this application
**does not** upgrade Oracle or make older backends compatible.

## Notes / limits

- This package targets **Ubuntu 22.04 amd64**, not ARM64, and depends on
  Ubuntu's shared graphical libraries.
- A real Ubuntu desktop + KiCad 10 integration test is still recommended,
  even after GitHub Actions build and virtual-display smoke tests succeed.
- The KiCad 10 PCM toolbar extension remains a separate Windows-focused ZIP.
  The Linux build provides the standalone desktop workspace and opens KiCad 10
  projects; it is **not** an installed Linux PCM toolbar plugin.
- Existing local workspaces are not deleted or converted by the installer.
- When launching from a terminal, application logs are saved under
  `~/.local/state/tauvsync/launcher.log` (or `$XDG_STATE_HOME/tauvsync`).
