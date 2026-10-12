# TAUV installation (KiCad 10, Windows)

**Beta PCM package:** Build and download the `TAUVSYNC-KiCad10-*.zip`
artifact from the GitHub Actions workflow associated with the beta branch.

1. Ensure KiCad 10.x is installed.
2. KiCad Project Manager → **Plugin and Content Manager** → **Install from File**.
3. Choose the TAUVSYNC PCM ZIP; do **not** unzip it manually.
4. PCB Editor → **Preferences → Plugins**: enable the KiCad IPC API server.
5. Restart PCB Editor.
6. **Tools → External Plugins → TAUV Team Projects**, or click the TAUV logo.
7. Enter your TAUV team email and password. The HTTPS server is prefilled.
8. Keep TAUV open or minimized while working on the managed checkout.

The PCM package has a bundled runtime; **no Python, Git or SSH installation**
is required for end users. Upgrade the plugin using a new PCM ZIP; never
delete your `TAUVSYNC` project folder to update.

**Do not remove the previous SWIG plugin until this IPC build is tested.**
If both variants appear on the toolbar, after confirming the IPC build works,
remove the previous `tauvsync_plugin` from your legacy scripting/plugins
folder, not from your managed checkout folder.

Legacy development installation and build commands are documented in
[README](../README.md).

**Current beta limitation:** Sync runs while the TAUV dashboard is open or
minimized. Closing the dashboard ends its sync thread.
