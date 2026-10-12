"""KiCad IPC executable entry point for TAUV desktop team projects.

PyInstaller uses this file as the frozen application's entry point. KiCad
passes its plugin directory as argv[1] for executable actions; TAUV doesn't
need to parse that argument to display the cloud project dashboard.
"""
from multiprocessing import freeze_support

from tauvsync.app import run


if __name__ == "__main__":
    freeze_support()
    run()
