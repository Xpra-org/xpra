# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.util.str_fn import print_nested_dict
from xpra.x11.bindings.display_source import init_display_source
from xpra.x11.bindings.randr import RandRBindings  # pylint: disable=no-name-in-module


def main() -> None:
    init_display_source()
    randr = RandRBindings()
    # print(randr.is_dummy16())
    print_nested_dict(randr.get_all_screen_properties())


if __name__ == "__main__":
    sys.exit(main())
