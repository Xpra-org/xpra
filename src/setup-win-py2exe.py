from distutils.core import setup
import py2exe

setup(
    name = 'Xpra',
    description = 'screen for X',
    version = '0.0.7.19',

    windows = [
                  {
                      'script': 'xpra/scripts/client_launcher.py',
                      'icon_resources': [(1, "xpra.ico")],
					  "dest_base": "Xpra-Launcher",
                  },
#                  {
#                      'script': 'xpra/scripts/main.py',
#                      'icon_resources': [(1, "xpra.ico")],
#                  }
              ],

    console = [
                  {
                      'script': 'xpra/scripts/main.py',
                      'icon_resources': [(1, "xpra.ico")],
					  "dest_base": "Xpra",
                  }
              ],

    options = {
                  'py2exe': {
                      'packages':'encodings',
                      'includes': 'cairo, pango, pangocairo, atk, glib, gobject, gio',
                      'dll_excludes': 'w9xpopen.exe'
                  }
              },

    data_files=[
                   'COPYING', 'website.url'
               ]
)
