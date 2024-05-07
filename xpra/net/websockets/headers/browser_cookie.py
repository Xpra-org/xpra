# This file is part of Xpra.
# Copyright (C) 2020 mjharkin
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import browser_cookie3  # @UnresolvedImport

from xpra.util.str_fn import strtobytes


def get_headers(host: str, _port: int) -> dict[bytes, bytes]:     # pylint: disable=unused-argument
    cookie_domain = host
    cookie_string = ''
    # get cookies for domain and all parent domains except tld
    while cookie_domain.count('.', 2):
        cj = browser_cookie3.load(domain_name=cookie_domain)
        for c in cj:
            cookie = c.name + "=" + c.value + "; "
            # add if cookie doesn't already exist from subdomain
            if c.name + "=" not in cookie_string:
                cookie_string += cookie
        cookie_domain = cookie_domain.split('.', 1)[1]
    return {
        b"Cookie": strtobytes(cookie_string),
    }
