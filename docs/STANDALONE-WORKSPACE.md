# TAUV 2.1 — standalone team workspace (Windows x64 beta)

This is a separate development branch, **not** a replacement for the working
client on main. It reuses the existing TAUVSYNC/Prism server and sync engine.

## Install and test

Download the Windows test artifact from the most recent successful GitHub
Actions run of the branch \`feature/tauv-standalone-launcher\`.

The artifact contains two **different** installers/launchers:

- \`TAUVSYNC.exe\`: **standalone application** — double-click to launch TAUV
  before opening KiCad. No external Python runtime required.
- \`TAUVSYNC-KiCad10-2.1.0.zip\`: install through KiCad 10 **Plugin and Content
  Manager → Install from File**. This opens the same TAUV desktop workspace
  from the PCB Editor toolbar.

**Do not extract the inner KiCad PCM ZIP manually.** You can place the standalone
\`TAUVSYNC.exe\` anywhere in your user directory and create a Windows shortcut to
it. It uses your existing stored settings and managed project folder.

## Workflow

1. Open standalone TAUV from Windows or using the KiCad PCB Editor plugin.
2. Sign into the existing HTTPS server using your team account. Previous
   securely remembered Windows DPAPI login may be reused automatically.
3. Browse or search existing active cloud projects; inspect cached PCB preview.
4. Click **New Project** and select Schematic + PCB / Schematic / PCB. TAUV
   generates blank KiCad 10 files, creates the initial cloud revision, downloads
   a managed checkout, then optionally opens it in KiCad.
5. Use **Open in KiCad** for existing projects. First open downloads the managed
   checkout automatically; subsequent opens reuse it.
6. Use **Import Existing** only for an already-created local project. The
   original project directory remains untouched.
7. Keep TAUV running or minimized for automatic sync. **Closing TAUV stops sync.**

Removed projects appear under the **Removed** filter with sync paused.
Existing local copies are never silently deleted.

## Safety

- New projects are not created locally in arbitrary destinations; they are
  created in a temporary archive, uploaded to the authenticated API, then
  downloaded into TAUV's managed workspace using the existing SyncEngine.
- If creation succeeds on the server but checkout fails, TAUV displays a
  recovery message. **Refresh the cloud list; do not click Create again.**
- No SSH keys, Git commands or Oracle credentials are needed on team PCs.
- Importing an existing design makes a managed copy and preserves the original.
- Version restore is an explicit action with confirmation; it publishes a new
  HEAD revision and preserves history.
- KiCad 10 and the backend have their own validations; manually verify new
  schematic and PCB templates open correctly before using them for real work.
- Current PCB preview uses cached backend thumbnail generation. Blank projects
  may legitimately show "No preview yet". The full schematic/PCB WebGL viewer
  is not embedded in this version.
- This release isn't code-signed; Windows SmartScreen may flag the unsigned exe.

## Developer build

Install \`customtkinter==5.2.2\`, \`pillow==11.3.0\`, \`pyinstaller\`,
and \`kicad-python==0.8.0\` in a Python 3.11+ Windows environment.
Run the commands listed in \`packaging/windows/README.md\`, with
\`--collect-all customtkinter\` for PyInstaller.

CI builds and tests the frozen exe with \`--self-test\` and packages the PCM ZIP.
No external GitHub API token or private backend materials are bundled.

## Difference from a GitHub fork

GitHub does not allow a repository to be forked under the same owning account.
The connected GitHub integration also cannot create a new fork/repository.
This is therefore a **fully isolated fork-like development branch**, with
a separate build artifact and review PR. The previous main branch remains intact.
