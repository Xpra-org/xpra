from distutils.core import setup
import py2exe

setup(
    name = 'xpra',
    description = 'screen for X',
    version = '0.0.7.9',

    windows = [
                  {
                      'script': 'xpra/scripts/client_launcher.py',
                      'icon_resources': [(1, "xpra.ico")],
                  },
                  {
                      'script': 'xpra/scripts/main.py',
                      'icon_resources': [(1, "xpra.ico")],
                  }
              ],

#    console = [
#                  {
#                      'script': 'xpra/scripts/main.py',
#                      'icon_resources': [(1, "xpra.ico")],
#                  }
#              ],

    options = {
                  'py2exe': {
                      'packages':'encodings',
                      'includes': 'cairo, pango, pangocairo, atk, gobject',
                  }
              },

    data_files=[
                   'COPYING'
               ]
)
