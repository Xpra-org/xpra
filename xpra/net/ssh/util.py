# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util.env import osexpand, envbool


LOG_EOF = envbool("XPRA_SSH_LOG_EOF", True)
# the default order matches the one used by openssh in `fill_default_options`:
KEY_FORMATS = os.environ.get("XPRA_SSH_KEY_FORMATS", "rsa,ecdsa,ecdsa_sk,ed25519,ed25519_sk,dsa").split(",")


def get_default_keyfiles() -> list[str]:
    dkf = os.environ.get("XPRA_SSH_DEFAULT_KEYFILES", None)
    if dkf is not None:
        return [x for x in dkf.split(os.pathsep) if x]
    from xpra.platform.paths import get_ssh_key_dirs
    for ssh_key_dir in get_ssh_key_dirs():
        keydir = osexpand(ssh_key_dir)
        if os.path.exists(keydir) and os.path.isdir(keydir):
            return [os.path.join(keydir, f"id_{fmt}") for fmt in KEY_FORMATS]
    return []
