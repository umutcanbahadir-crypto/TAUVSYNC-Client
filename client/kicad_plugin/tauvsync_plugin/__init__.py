"""PCB Editor ActionPlugin bridge for the TAUVSYNC sync client.

Use the installer in client/kicad_plugin/install.py to bundle the tauvsync
package into the plugin directory.
"""
try:
    from .action import TauvsyncAction
    TauvsyncAction().register()
except ImportError:
    # Non-KiCad environments lack pcbnew; the desktop sync client still works.
    pass
