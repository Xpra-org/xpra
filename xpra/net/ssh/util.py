# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.util.env import osexpand


# workaround incompatibility between paramiko and gssapi:
class nomodule_context:
    __slots__ = ("module_name", "saved_module")

    def __init__(self, module_name):
        self.module_name = module_name

    def __enter__(self):
        self.saved_module = sys.modules.get(self.module_name)
        # noinspection PyTypeChecker
        sys.modules[self.module_name] = None        # type: ignore[assignment]

    def __exit__(self, *_args):
        if sys.modules.get(self.module_name) is None:
            if self.saved_module is None:
                sys.modules.pop(self.module_name, None)
            else:
                sys.modules[self.module_name] = self.saved_module

    def __repr__(self):
        return f"nomodule_context({self.module_name})"


def get_default_keyfiles() -> list[str]:
    dkf = os.environ.get("XPRA_SSH_DEFAULT_KEYFILES", None)
    if dkf is not None:
        return [x for x in dkf.split(os.pathsep) if x]
    return [osexpand(os.path.join("~/", ".ssh", keyfile)) for keyfile in ("id_ed25519", "id_ecdsa", "id_rsa", "id_dsa")]
