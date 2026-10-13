# TAUV standalone Windows build

The package contains a frozen Windows TAUVSYNC.exe. End users need only KiCad
10 and the PCM ZIP; Python, Git, and SSH are not needed.

Developer build on Windows:

```powershell
py -3.12 -m pip install pyinstaller kicad-python==0.8.0
py -3.12 scripts/generate_windows_icon.py
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --icon client/tauvsync/resources/tauv_app.ico --name TAUVSYNC --paths client --add-data "client/tauvsync/resources;tauvsync/resources" client/launcher.py
py -3.12 packaging/build_pcm.py
```

Install the resulting ZIP with **KiCad 10 -> Plugin and Content Manager ->
Install from File**. Enable **Preferences -> Plugins -> KiCad IPC API** if it
is disabled, and restart PCB Editor. The TAUV Team Projects action appears
under External Plugins. Data and credentials are stored outside the PCM
installation and survive plugin upgrades.

**Important:** The legacy SWIG plugin can create a duplicate toolbar button.
Remove the previous per-user `tauvsync_plugin` install after confirming the
new IPC plugin works, without deleting `~/TAUVSYNC` project folders.

This first release package targets Windows x64 only. Build and GUI activation
must be validated on an actual KiCad 10 installation before team-wide release.
