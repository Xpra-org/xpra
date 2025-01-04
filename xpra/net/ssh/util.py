# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util.env import osexpand, envbool


LOG_EOF = envbool("XPRA_SSH_LOG_EOF", True)


def get_default_keyfiles() -> list[str]:
    dkf = os.environ.get("XPRA_SSH_DEFAULT_KEYFILES", None)
    if dkf is not None:
        return [x for x in dkf.split(os.pathsep) if x]
    return [osexpand(os.path.join("~/", ".ssh", keyfile)) for keyfile in ("id_ed25519", "id_ecdsa", "id_rsa", "id_dsa")]
