# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Printing PDF in landscape orientation does not work properly on OSX,
# so we use PS instead:
DEFAULT_MIMETYPES = ["application/postscript"]

from xpra.platform.pycups_printing import (
    get_printers,
    print_files,
    printing_finished,
    init_printing,
    cleanup_printing,
    get_info,
)

assert get_printers and print_files and printing_finished and init_printing and cleanup_printing and get_info # type: ignore[truthy-function]
