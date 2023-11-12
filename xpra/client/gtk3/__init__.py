# This file is part of Xpra.
# Copyright (C) 2013-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

try:
    from xpra.gtk_common.gtk_util import init_display_source
    init_display_source()
except:
    # for some strange reason,
    # this may fail on MacOS when running py2app
    # and we don't care then
    pass
