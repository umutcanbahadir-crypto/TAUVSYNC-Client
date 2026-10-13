# TAUVSYNC for Ubuntu 22.04 LTS (amd64)

This is a **native Linux build**, produced from the same v2.2.1 Python client as
Windows, on GitHub's `ubuntu-22.04` x86_64 runner. It does not run the Windows
EXE under Wine. It is a beta and requires a graphical GNOME/X11/XWayland
desktop session; headless/SSH servers are not supported as desktop clients.

## One-click download and graphical installation (recommended)

### [⬇ Download TAUVSYNC for Ubuntu 22.04 — .deb](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/tauvsync_2.2.1_amd64.deb)

1. Click **Download TAUVSYNC for Ubuntu 22.04** above. Your browser downloads `tauvsync_2.2.1_amd64.deb`; you do not need to clone this repository.
2. Open **Files → Downloads** in Ubuntu and double-click the downloaded `.deb`. If necessary, right-click → **Open With → Software Install**.
3. Choose **Install**, authenticate with your Ubuntu password, then find **TAUVSYNC** in **Show Applications**.

This installs the app and desktop launcher, with no command-line steps. It does not install KiCad itself; **KiCad 10 is required to edit projects**.

If your desktop has no graphical package installer, use the terminal fallback below. Run it **from the folder holding the downloaded file**, or give the complete file path.

```bash
cd ~/Downloads
sudo apt install ./tauvsync_2.2.1_amd64.deb
tauvsync
```

For optional download integrity verification, also get the [SHA-256 checksum file](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/tauvsync_2.2.1_amd64.deb.sha256) and, from the Downloads directory, run `sha256sum -c tauvsync_2.2.1_amd64.deb.sha256`. Both files must exist in the same directory. The installer does not touch existing local TAUVSYNC projects.

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
