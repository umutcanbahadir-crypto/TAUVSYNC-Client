# TAUVSYNC Client

KiCad **10** desktop plugin and automatic project synchronizer for a separately managed TAUVSYNC / KiCAD Prism team server.

**This public repository contains only client source and client tests.** It includes no server source, GitHub token, SSH private key, accounts, database or deployment configuration. Cloning this repository does not grant access to anyone's Prism projects.

**Status:** Team-testing release; Python-based installation, not a signed Windows installer. Supports KiCad 10 only.

## Install on Windows 10/11

1. Install **KiCad 10.0.x**. For team compatibility, ask the administrator which KiCad 10 patch version the server uses.
2. Install **Python 3.11+** with Tkinter and Windows `py` launcher from [python.org](https://www.python.org/downloads/windows/). Verify with PowerShell:

   ```powershell
   py -3 --version
   py -3 -c "import tkinter; print('Tkinter OK')"
   ```

3. Click **Code → Download ZIP** on this GitHub repository and extract it, or clone without any token:

   ```powershell
   git clone https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client.git
   cd TAUVSYNC-Client
   ```

   For ZIP users, open the extracted folder that contains the `client` directory. Type `powershell` in File Explorer's address bar to open a terminal there.

4. **Close KiCad and PCB Editor**. From the repository root run:

   ```powershell
   py -3 client/kicad_plugin/install.py 10.0
   ```

5. Restart **KiCad 10 → PCB Editor → Tools → External Plugins → TAUVSYNC — Team Projects**.
6. Enter the **current HTTPS Prism server address provided by your administrator**, your personal Prism email/password, and a local workspace such as `C:\Users\YOUR_USERNAME\TAUVSYNC`. **Leave automatic SSH disabled** when using HTTPS. Click **Log in**.
7. Open a shared project from TAUVSYNC and edit that downloaded **managed copy** in KiCad. Keep TAUVSYNC running/minimized so changes synchronize.

### What synchronization does

- Saved project changes are automatically published after about **8 seconds** of inactivity. The client checks for new remote revisions about every **5 seconds** while running.
- Incoming revisions are not installed over unsaved/local changes or while KiCad PCB/Schematic Editors are open.
- Divergent edits are preserved as separate revisions for manual conflict resolution; they are not automatically merged.
- Uploading an existing local KiCad project leaves its original folder intact and creates a **separate managed checkout**. Continue editing the managed checkout if you want auto-sync.
- Only authorized Prism Designer/Admin users can publish; Viewer users can read. The server enforces account permissions.
- Windows **Remember email and password** uses Windows DPAPI encryption; do not share user accounts.
- Use a stable HTTPS server URL for team operation. Cloudflare Quick Tunnel links are temporary.

### Update

Close TAUVSYNC and KiCad. Download the latest ZIP or run `git pull --ff-only` in the clone, then reinstall:

```powershell
py -3 client/kicad_plugin/install.py 10.0
```

The installer uses your per-user KiCad plugins folder, supports redirected/OneDrive Documents and backs up older plugin versions.

## Troubleshooting

| Problem | Resolution |
| --- | --- |
| `py` missing | Install the Windows Python launcher; reopen PowerShell. |
| `No module named tkinter` | Install Python with Tcl/Tk. |
| Plugin is missing | Restart KiCad **PCB Editor**, check KiCad 10 and rerun the installer. |
| Login fails | Confirm your Prism account and the administrator-provided HTTPS URL; complete any password-change prompt on Prism's website. |
| No projects | Ask your administrator to confirm your Prism account and projects. |
| Saves not syncing | Work in the **managed checkout**, keep TAUVSYNC running, and use a Designer/Admin role. |
| New revision not installed | Close PCB Editor and Schematic Editor when the checkout is unchanged. |
| Conflict | Preserve local work as an alternate revision before explicitly choosing the latest server copy. |

## Developers

The KiCad PCB Editor launcher is at `client/kicad_plugin/`, and the standalone Tkinter client is at `client/tauvsync/`. Tests run locally without requiring a real server:

```powershell
py -3 -m unittest discover -s client/tests -v
py -3 -m compileall -q client
```

Optional built-in SSH forwarding exists only for users already authorized to access their own server over SSH. Normal team clients use HTTPS. No Oracle server address or SSH key ships in this repository.

**Security:** No access tokens are required to download this public repository. Do not commit local state, passwords, cookies, SSH keys, `.env` files or real KiCad projects. Server access control must be enforced server-side; client code is public by design.

**Licensing:** No separate reuse license for TAUVSYNC client code has been declared yet. Public source visibility does not itself grant an open-source license. This repository does not copy the upstream KiCAD Prism server application.
