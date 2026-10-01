# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import List

from xpra.os_util import osexpand, nomodule_context


#workaround incompatibility between paramiko and gssapi:
class nogssapi_context(nomodule_context):

    def __init__(self):
        super().__init__("gssapi")


def get_default_keyfiles() -> List[str]:
    dkf = os.environ.get("XPRA_SSH_DEFAULT_KEYFILES", None)
    if dkf is not None:
        return [x for x in dkf.split(os.pathsep) if x]
    #the default order matches the one used by openssh in `fill_default_options`:
    keyfiles = ("id_rsa", "id_ecdsa", "id_ecdsa_sk", "id_ed25519", "id_ed25519_sk", "id_dsa")
    return [osexpand(os.path.join("~/", ".ssh", keyfile)) for keyfile in keyfiles]

