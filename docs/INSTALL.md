# Installation quick reference

**Public GitHub client:** https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client

On Windows with KiCad 10 and Python 3.11+ (Tkinter enabled), run:

```powershell
git clone https://github.com/umutcanbahadir-crypto/TAUVSYNC-Client.git
cd TAUVSYNC-Client
py -3 client/kicad_plugin/install.py 10.0
```

Restart KiCad 10 PCB Editor and choose **Tools → External Plugins → TAUVSYNC — Team Projects**.
Enter the **HTTPS Prism URL from your administrator** and sign in with your **own Prism credentials**. The GitHub URL is not the Prism server address. No GitHub token is required to install.

See [README](../README.md) for the full guide, synchronization behavior and troubleshooting.
