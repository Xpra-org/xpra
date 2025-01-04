# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# posix: assume cups support (no overrides needed here)
from xpra.platform.pycups_printing import (
    get_printers,
    print_files,
    printing_finished,
    init_printing,
    cleanup_printing,
    get_info,
)

for x in (get_printers, print_files, printing_finished, init_printing, cleanup_printing, get_info):
    assert callable(x), f"{x} is not callable"
