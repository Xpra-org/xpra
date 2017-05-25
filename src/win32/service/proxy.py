#!/usr/bin/env python

import os
import sys

os.environ["XPRA_REDIRECT_OUTPUT"] = "1"

from xpra.platform import init, set_default_name
set_default_name("Xpra-Proxy")
init()

from xpra.scripts.main import main
sys.exit(main(sys.argv[0], sys.argv))
