# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

# cryptography must see this before macOS components import it
if sys.platform == "darwin":
    import os
    os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")
