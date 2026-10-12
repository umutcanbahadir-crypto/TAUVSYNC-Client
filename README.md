# TAUV — KiCad Team Projects

A team project browser and automatic synchronization client for **KiCad 10**
and the TAUVSYNC/Prism HTTPS backend.

**Status:** `2.0.0-beta.1` implementation branch, Windows x64 testing release.
The existing `main` installation remains supported until the PCM build has
been tested inside KiCad on a clean machine.

## One-package installation (Windows beta)

The intended end-user installation requires **no separate Python, Git or SSH**.

1. Download the tested `TAUVSYNC-KiCad10-2.0.0-beta.1.zip` PCM package from
   the Windows build artifact or a future tagged release.
2. Open KiCad 10 **Plugin and Content Manager → Install from File**.
3. If KiCad's IPC API is disabled, enable it in **Preferences → Plugins**
   and restart PCB Editor. KiCad 10 only exposes these plugins in PCB Editor.
4. Open **PCB Editor → Tools → External Plugins → TAUV Team Projects**,
   or use the plugin's toolbar button.
5. Sign in with your existing team account. The server field defaults to
   `https://tauvsync-gateway.umutcanbahadir.workers.dev`.
6. Choose the local TAUVSYNC workspace and open a managed project.

**Important:** The executable PCM integration has not yet been validated on a
real KiCad 10 installation. Do not uninstall an existing working plugin until
the new one starts, authenticates and synchronizes a disposable test project.

## What the extension provides

- TAUV-branded dashboard and KiCad toolbar icon from the team's supplied logo.
- HTTPS-only login using the existing backend accounts and permissions.
- Optional remembered login encrypted with Windows DPAPI (no plaintext passwords).
- Browse, search, upload and open shared KiCad projects.
- Automatically detect and publish saved changes (settling time ~8 seconds).
- Poll incoming revisions (~5 seconds) and protect open editors/local changes.
- Download historical snapshots or restore an older revision as a new head.
- Pause synchronization when a project is removed from the web workspace,
  **preserving local copies**.
- Multiple launches focus the existing window on Windows rather than start
  a second synchronization engine.

**Synchronization runs while the TAUV dashboard stays open or minimized.**
Closing it stops synchronization. A separate tray agent, resumable upload,
automatic conflict merge, and project-specific KiCad editor detection are
future milestones and have not been implemented in this beta.

The client never modifies the original local project folder during an initial
upload; it creates a separate **managed checkout**. Continue editing the
managed checkout for automatic publishing.

## Developer workflow (Windows)

The repository is public client source only. It contains no server credentials
or private key material. The backend is deployed separately.

Legacy development installation (still supported on `main`):

```powershell
py -3.12 client/kicad_plugin/install.py 10.0
```

Build self-contained Windows executable and PCM ZIP on this development branch:

```powershell
py -3.12 -m pip install pyinstaller kicad-python==0.8.0
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name TAUVSYNC --paths client --add-data "client/tauvsync/resources;tauvsync/resources" client/launcher.py
py -3.12 packaging/build_pcm.py
```

CI also builds and uploads the PCM ZIP from Windows runners.

Run unit and packaging tests on any platform:

```powershell
py -3.12 -m unittest discover -s client/tests -v
py -3.12 -m compileall -q client packaging
```

The packaging configuration is in `packaging/pcm/plugin.json` and
`packaging/build_pcm.py`. No runtime Python is needed for the packaged
`.exe`; Python is still required to **build** it.

### Migration and data protection

The upgrade reuses `~/.tauvsync-client.json`, Windows DPAPI credentials, and
the user's local managed workspace. Obsolete SSH settings from previous
releases are ignored and dropped when settings are next saved. The development
branch does not delete checkouts, state files or passwords on upgrade.

If the legacy SWIG and new IPC variants are both installed, KiCad may show
duplicate actions. Remove the legacy `tauvsync_plugin` from KiCad's user
scripting/plugins folder **only after** confirming the IPC variant works.
Do not delete the managed project workspace.

### Constraints

- Supports KiCad **10.0.x** (Windows x64 package first).
- The KiCad 10 IPC plugin cannot add UI to the Project Manager home screen.
- Cloudflare gateway limits may reject uploads before the server's 512 MiB
  archive maximum. Size and transfer handling needs end-to-end testing.
- Conflict resolution keeps both designs; it does not merge schematics/PCBs.
- Removed historical projects with missing Git repositories cannot be restored
  from SQLite metadata alone.
- PCM publishing to the official KiCad repository requires a compatible
  open-source license. No such license is declared for this source repository;
  the current package is a testing ZIP for direct/private installation.
