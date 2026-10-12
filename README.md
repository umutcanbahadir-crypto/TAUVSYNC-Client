# TAUVSYNC Client — TAUV Team Workspace

**A standalone Windows project manager and KiCad 10 synchronization extension.**
Browse shared projects, preview rendered PCB images, create new KiCad designs, download existing projects, and open them in KiCad 10. Uploading an existing project is optional.

> **Version 2.1.1 — Windows 10/11 x64 beta.** No separate Python, Git, or SSH installation is required for users. The executable is not code-signed; Windows SmartScreen may display a warning.

## Download for Windows

### [Download TAUVSYNC.exe directly](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.1.1/TAUVSYNC.exe)

**[All downloads and release notes](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/tag/v2.1.1)** | [KiCad 10 plugin ZIP](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.1.1/TAUVSYNC-KiCad10-2.1.1.zip) | [Windows EXE checksum](https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client/releases/download/v2.1.1/TAUVSYNC.exe.sha256)

The standalone EXE and KiCad plugin are **two ways to open the same TAUV workspace**. Install either or both.

### Standalone launcher (recommended)

1. Download **TAUVSYNC.exe** using the link above. It is the actual executable, **not** a ZIP inside a GitHub Actions artifact.
2. Save the executable in a folder you control, such as `%LOCALAPPDATA%\Programs\TAUVSYNC\`. You may pin a shortcut to Start/Taskbar.
3. Run `TAUVSYNC.exe`, sign in using **your own authorized TAUVSYNC team account**, and choose a local workspace directory.
4. Browse shared projects or select **New Project** to create the first cloud revision without using KiCad first.
5. Use **Open in KiCad** to download the managed copy, if necessary, and open it specifically in **KiCad 10**. Keep TAUV running or minimized while editing for synchronization.

### Optional KiCad 10 toolbar extension

1. Install KiCad **10.0.x**.
2. Download `TAUVSYNC-KiCad10-2.1.1.zip` directly from the link above. **Do not extract this ZIP.**
3. In KiCad, open **Plugin and Content Manager → Install from File** and select the downloaded ZIP.
4. Enable KiCad's IPC API under PCB Editor **Preferences → Plugins**, if disabled, and restart PCB Editor.
5. Open **PCB Editor → Tools → External Plugins → TAUV Team Projects**, or click the TAUV toolbar icon.

**If upgrading from the old Python Action Plugin:** keep the old version until the IPC extension works, then remove the obsolete `tauvsync_plugin` launcher from KiCad's per-user scripting/plugin folder. **Never delete your local TAUVSYNC workspace.**

## Features

- **Create Projects:** TAUV creates new schematic, PCB or combined KiCad projects, uploads cloud revision r1 and downloads a synchronized managed checkout.
- **Shared workspace:** Browse and search project names, revisions and the latest revision author.
- **PCB previews:** Reuses cached PCB thumbnails already rendered by the Prism server; new/blank projects may have no thumbnail yet.
- **Open in KiCad 10:** Uses KiCad 10's executable instead of Windows' default `.kicad_pro` association, which may point to KiCad 9.
- **Import Existing:** Copies an existing local KiCad project into a separate managed checkout; original files remain unchanged.
- **Duplicate naming:** New or imported projects get names such as `Buck (1)` or `Buck (2)` when needed. Histories are not merged automatically.
- **Automatic synchronization:** Detects saved changes and remote revisions while TAUV is running, preserving divergent/local edits rather than overwriting them silently.
- **Revision history:** Download earlier snapshots and, with the necessary permissions, explicitly restore a historical revision as a new latest revision.
- **Project removal:** Refreshes the server list; removed projects stop synchronizing and existing local files are preserved.
- **Account security:** HTTPS sign-in with the existing server. Optional remembered login uses Windows DPAPI.

**Current limitations:** Background sync stops when TAUV exits (minimizing is fine); conflict resolution is manual; no integrated full schematic/PCB renderer or resumable transfer support. Test new-project templates on a disposable design before using them for production. This is a Windows x64 team-testing release, not a signed installer.

## Connection and privacy

The server endpoint is configured in the client, but **the client contains no hardcoded account, signup password, GitHub token, SSH private key, or Oracle server credential**. The executable does **not** provide project access by itself; your own authorized account is required. The **TAUVSYNC server and its database are maintained separately** and are not published in this repository.

Local passwords may be remembered with Windows DPAPI under the current Windows account. Do not share login credentials or synchronized workspace directories.

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

This public repository holds the client application source and tests, **not the private server**. The Windows EXE and KiCad PCM ZIP are compiled on GitHub Actions and published as GitHub Release assets—not committed as binaries to the source tree.

```powershell
git clone https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client.git
cd TAUVSYNC-Client
py -3.12 -m unittest discover -s client/tests -v
py -3.12 scripts/check_public_secrets.py
```

To build on Windows:

```powershell
py -3.12 -m pip install pyinstaller kicad-python==0.8.0 customtkinter==5.2.2 pillow==11.3.0
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name TAUVSYNC --paths client --collect-all customtkinter --add-data "client/tauvsync/resources;tauvsync/resources" client/launcher.py
py -3.12 packaging/build_pcm.py
```

For a new release, update the version in `packaging/build_pcm.py`, the PCM tests, and the pinned version references in the GitHub Actions release workflow and README; then run all checks before publishing. Existing release assets are not overwritten.

**Security:** Never commit `.env`, passwords, session cookies, project archives, account data or SSH keys.

**Licensing:** No separate reuse license has been declared for this repository. Public source availability does not by itself grant permission to redistribute or relicense it.
