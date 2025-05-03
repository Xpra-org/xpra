# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.x11.bindings.xwayland import isxwayland


def main() -> None:
    display = os.environ.get("DISPLAY", "NULL")
    print(f"isxwayland({display})={isxwayland(display)}")


if __name__ == "__main__":
    main()
