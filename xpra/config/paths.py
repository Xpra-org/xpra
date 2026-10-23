#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Discovery of installed documentation and HTML5 resources."""

import os
from xpra.os_util import POSIX


def find_html5_path(page="connect.html") -> str:
    from xpra.platform.paths import get_resources_dir, get_app_dir
    return valid_html_path(
        os.path.join(get_resources_dir(), "html5", page),
        os.path.join(get_resources_dir(), "www", page),
        os.path.join(get_app_dir(), "www", page),
    )


def find_docs_path() -> str:
    from xpra.platform.paths import get_resources_dir, get_app_dir
    paths = []
    prefixes = {get_resources_dir(), get_app_dir()}
    if POSIX:
        prefixes.add("/usr/share")
        prefixes.add("/usr/local/share")
    for prefix in prefixes:
        for parts in (
                ("doc", "xpra", "index.html"),
                ("xpra", "doc", "index.html"),
                ("doc", "index.html"),
                ("doc", "index.html"),
        ):
            paths.append(os.path.join(prefix, *parts))
    return valid_html_path(*paths)


def valid_html_path(*path_options: str) -> str:
    for f in path_options:
        af = os.path.abspath(f)
        if os.path.exists(af) and os.path.isfile(af):
            return af
    return ""
