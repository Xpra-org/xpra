# This file is part of Xpra.
# Copyright (C) 2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# duplicated from SimpleHTTPRequestHandler
# so that we can re-use it from the quic handler
# and also so that we can customize it more easily

import os
import sys
import html
from io import BytesIO
from urllib.parse import quote, unquote


def list_directory(path: str) -> tuple[int, dict[str, str], bytes]:
    try:
        dirlist = os.listdir(path)
    except OSError:
        return 404, {}, b"No permission to list directory"
    dirlist.sort(key=lambda a: a.lower())
    r = []
    try:
        displaypath = unquote(path, errors='surrogatepass')
    except UnicodeDecodeError:
        displaypath = unquote(path)
    displaypath = html.escape(displaypath, quote=False)
    enc = sys.getfilesystemencoding()
    title = f"Directory listing for {displaypath}"
    r.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" '
             '"http://www.w3.org/TR/html4/strict.dtd">')
    r.append('<html>\n<head>')
    r.append(f'<meta http-equiv="Content-Type" content="text/html; charset={enc}">')
    r.append(f'<title>{title}</title>\n</head>')
    r.append(f'<body>\n<h1>{title}</h1>')
    r.append('<hr>\n<ul>')
    for name in dirlist:
        fullname = os.path.join(path, name)
        displayname = linkname = name
        # Append / for directories or @ for symbolic links
        if os.path.isdir(fullname):
            displayname = name + "/"
            linkname = name + "/"
        if os.path.islink(fullname):
            displayname = name + "@"
            # Note: a link to a directory displays with @ and links with /
        href = quote(linkname, errors='surrogatepass')
        link = html.escape(displayname, quote=False)
        r.append(f'<li><a href="{href}">{link}</a></li>')
    r.append('</ul>\n<hr>\n</body>\n</html>\n')
    encoded = '\n'.join(r).encode(enc, 'surrogateescape')
    f = BytesIO()
    f.write(encoded)
    contents = f.getvalue()
    f.close()
    return 200, {
        "Content-type": f"text/html; charset={enc}",
        "Content-Length": str(len(encoded)),
    }, contents
