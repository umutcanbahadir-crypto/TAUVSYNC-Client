# TAUVSYNC Client — TAUV Team Workspace

**A standalone Windows/Linux project manager and KiCad 10 synchronization extension.**
Browse shared projects, preview rendered PCB images, create new KiCad designs, download existing projects, and open them in KiCad 10. Uploading an existing project is optional.

> **Version 2.2.1 — Windows 10/11 x64 and Ubuntu 22.04 amd64 beta.** No separate Python, Git, or SSH installation is required for users. Windows executable is not code-signed; Windows SmartScreen may display a warning.

## Download TAUVSYNC

### [⬇ Download for Ubuntu 22.04 — .deb installer](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/tauvsync_2.2.1_amd64.deb)

### [⬇ Download for Windows 10/11 — TAUVSYNC.exe](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/TAUVSYNC.exe)

**Direct downloads:** Click the link for your operating system. No Git, Python, terminal commands, or GitHub Actions account is needed to download the application.

[All v2.2.1 release files](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/tag/v2.2.1) · [Linux checksum](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/tauvsync_2.2.1_amd64.deb.sha256) · [Windows checksum](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/TAUVSYNC.exe.sha256) · [KiCad 10 Windows plugin ZIP](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/TAUVSYNC-KiCad10-2.2.1.zip)

### Ubuntu 22.04 — graphical installation

1. Click **Download for Ubuntu 22.04** above. Your browser saves `tauvsync_2.2.1_amd64.deb` to Downloads.
2. Open **Files → Downloads** and **double-click the .deb**. If prompted, choose **Open With → Software Install**.
3. Click **Install**, authenticate with your Ubuntu password, and launch **TAUVSYNC** from the Applications menu.

You do not need to use `apt`, `sha256sum`, or Terminal for the normal graphical installation. The optional [Linux checksum](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.2.1/tauvsync_2.2.1_amd64.deb.sha256) can be used for manual integrity verification. For a command-line fallback and KiCad 10 setup, see the [Ubuntu 22.04 guide](docs/LINUX-UBUNTU22.04.md).

The Ubuntu package is for **x86_64/amd64**, not ARM64. It includes the desktop-menu launcher and file-manager integration. **KiCad 10 must be installed separately** for project editing; an older default KiCad does not meet the requirement. The Linux build is the standalone app; KiCad's Windows-only PCM extension is a separate download.

### Windows — standalone launcher (recommended)

The Windows EXE and optional KiCad 10 PCM plugin are two ways to open the same TAUV workspace.

1. Download **TAUVSYNC.exe** using the link above. It is the actual executable, **not** a ZIP inside a GitHub Actions artifact.
2. Save the executable in a folder you control, such as `%LOCALAPPDATA%\Programs\TAUVSYNC\`. You may pin a shortcut to Start/Taskbar.
3. Run `TAUVSYNC.exe`, sign in using **your own authorized TAUVSYNC team account**, and choose a local workspace directory.
4. Browse shared projects or select **New Project** to create the first cloud revision without using KiCad first.
5. Use **Open in KiCad** to download the managed copy, if necessary, and open it specifically in **KiCad 10**. Keep TAUV running or minimized while editing for synchronization.
6. Once downloaded, select a project and click **Open Folder** to view its managed checkout in Windows Explorer. Cloud-only projects have this action disabled; locally retained copies of removed projects can still be opened. This does not acquire a lock or synchronize edits.

### Optional KiCad 10 toolbar extension

1. Install KiCad **10.0.x**.
2. Download `TAUVSYNC-KiCad10-2.2.1.zip` directly from the link above. **Do not extract this ZIP.**
3. In KiCad, open **Plugin and Content Manager → Install from File** and select the downloaded ZIP.
4. Enable KiCad's IPC API under PCB Editor **Preferences → Plugins**, if disabled, and restart PCB Editor.
5. Open **PCB Editor → Tools → External Plugins → TAUV Team Projects**, or click the TAUV toolbar icon.

**If upgrading from the old Python Action Plugin:** keep the old version until the IPC extension works, then remove the obsolete `tauvsync_plugin` launcher from KiCad's per-user scripting/plugin folder. **Never delete your local TAUVSYNC workspace.**

## Features

- **Automatic update checks:** Every launch checks the public GitHub Releases feed in the background, including beta versions. If a newer compatible Windows or Linux package is published, TAUV offers a link to the official release. It never silently installs or replaces files, and startup/login/sync continue when GitHub is unavailable.
- **Create Projects:** TAUV creates new schematic, PCB or combined KiCad projects, uploads cloud revision r1 and downloads a synchronized managed checkout.
- **Shared workspace:** Browse and search project names, revisions and the latest revision author.
- **PCB previews:** Reuses cached PCB thumbnails already rendered by the Prism server; new/blank projects may have no thumbnail yet.
- **Open in KiCad 10:** Uses KiCad 10's executable instead of Windows' default `.kicad_pro` association, which may point to KiCad 9.
- **Open Folder:** Opens the selected project's existing managed local directory in Windows Explorer or the Linux file manager without creating, downloading, modifying, or syncing project data. Available only after a local checkout exists.
- **Import Existing:** Copies an existing local KiCad project into a separate managed checkout; original files remain unchanged.
- **Duplicate naming:** New or imported projects get names such as `Buck (1)` or `Buck (2)` when needed. Histories are not merged automatically.
- **Automatic synchronization:** Detects saved changes and remote revisions while TAUV is running, preserving divergent/local edits rather than overwriting them silently.
- **Revision history:** Download earlier snapshots and, with the necessary permissions, explicitly restore a historical revision as a new latest revision.
- **Project removal:** Refreshes the server list; removed projects stop synchronizing and existing local files are preserved.
- **Account security:** HTTPS sign-in with the existing server. Optional remembered login uses Windows DPAPI or Linux Secret Service; passwords are never saved as plaintext in preferences.

**Exclusive editing locks (2.2.1):** Opening a shared project as a Designer/Admin acquires a server-side project lock. The current owner is shown to teammates; other users can inspect thumbnails or download historical snapshots but cannot open the shared working copy or publish. TAUV renews the 180-second lease every 30 seconds while running. Close all KiCad editors, finish synchronization and choose **Release lock** so teammates can edit. An Admin can force-release abandoned locks through the authenticated API. If TAUV crashes, the lease expires automatically. Local files cannot be technically prevented from being edited offline.

**Required server upgrade:** v2.2.1 needs the corresponding TAUVSYNC backend with `/api/tauvsync/projects/{id}/edit-lock` endpoints. **Deploy the new backend before using this client for shared edits.** Older clients will be refused revision uploads after enforcement is enabled. The Windows executable does not deploy or update Oracle.

**Current limitations:** Background sync stops when TAUV exits (minimizing is fine); conflict resolution is manual; no integrated full schematic/PCB renderer or resumable transfer support. Test new-project templates on a disposable design before using them for production. These Windows/Linux packages are beta builds, not signed installers.

## Connection and privacy

The server endpoint is configured in the client, but **the client contains no hardcoded account, signup password, GitHub token, SSH private key, or Oracle server credential**. The executable does **not** provide project access by itself; your own authorized account is required. The **TAUVSYNC server and its database are maintained separately** and are not published in this repository.

Local passwords may be remembered with Windows DPAPI or an unlocked Linux Secret Service keyring. Do not share login credentials or synchronized workspace directories.

Public-repository CI runs automated tests, a frozen Windows EXE startup smoke test, KiCad package schema checks, and a check for committed credentials. These checks reduce risk but are not a complete security audit.

## Troubleshooting

| Problem | Suggested action |
| --- | --- |
| SmartScreen warns about the executable | This beta is unsigned; verify the asset's SHA-256 checksum and download only from this repository's Releases page. |
| Login fails | Confirm your team account, server URL, and permissions in the TAUVSYNC website. |
| No projects listed | Confirm your account can access the team workspace and check the Removed filter. |
| Saved changes do not sync | Keep TAUV running, edit the **managed checkout**, and verify Designer/Admin access. |
| Project opens in the wrong KiCad version | Install KiCad 10 or set `TAUV_KICAD10_EXE` to the path of KiCad 10's `kicad.exe`. |
| Existing plugin appears twice | Remove the legacy SWIG plugin **only after** validating the new IPC version; preserve your project directory. |
| New project has no preview | Prism may not have rendered one yet, especially for an empty PCB. |

For more details see [Standalone workspace guide](docs/STANDALONE-WORKSPACE.md) and [KiCad installation guide](docs/INSTALL.md).

## Developers

This public repository holds the client application source and tests, **not the private server**. Windows EXE, Ubuntu .deb and portable Linux archive, and KiCad PCM ZIP are compiled on GitHub Actions and published as GitHub Release assets—not committed as binaries to the source tree.

```powershell
git clone https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client.git
cd TAUVSYNC-Client
py -3.12 -m unittest discover -s client/tests -v
py -3.12 scripts/check_public_secrets.py
```

To build on Windows:

```powershell
py -3.12 -m pip install pyinstaller kicad-python==0.8.0 customtkinter==5.2.2 pillow==11.3.0
py -3.12 scripts/generate_windows_icon.py
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --icon client/tauvsync/resources/tauv_app.ico --name TAUVSYNC --paths client --collect-all customtkinter --add-data "client/tauvsync/resources;tauvsync/resources" client/launcher.py
py -3.12 packaging/build_pcm.py
```

For a new release, update the version in `client/tauvsync/update_check.py` and `packaging/build_pcm.py`, the PCM tests, and the pinned version references in the GitHub Actions release workflow and README; then run all checks before publishing. Existing release assets are not overwritten.

**Security:** Never commit `.env`, passwords, session cookies, project archives, account data or SSH keys.

**Licensing:** No separate reuse license has been declared for this repository. Public source availability does not by itself grant permission to redistribute or relicense it.
