#!/usr/bin/env python

# normally, the win32 platform code redirects the output to a log file
# this script disables that and is compiled as "Xpra_cmd.exe"
# instead of "Xpra.exe"

import sys
from xpra.win32 import set_redirect_output
set_redirect_output(False)

from xpra.scripts.main import main 
code = main("Xpra.exe", sys.argv)
sys.exit(code)
