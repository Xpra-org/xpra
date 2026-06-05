# Source Code Information

See also [dependencies](./Dependencies.md).

These statistics do not include the build or packaging files.

The binary package sizes vary widely, see for example [lightweight win32 installations](https://github.com/Xpra-org/xpra/issues/4100).


# Metrics

| Ref | Branch Date | Files | SLOC | Py Files | Py SLOC | Pyx Files | Pyx SLOC | Modules | Codecs | Commits Since Base |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| master | 2026-06-05 | 1,073 | 191,733 | 910 | 150,167 | 106 | 30,793 | 1,016 | 38 | 0 |
| v6.5.x | 2026-05-14 | 994 | 177,593 | 852 | 144,087 | 98 | 28,230 | 950 | 32 | 1 |
| v6.4.x | 2026-01-28 | 905 | 165,635 | 780 | 134,818 | 90 | 26,542 | 870 | 31 | 122 |
| v5.1.x | 2023 | 672 | 150,079 | 571 | 120,846 | 69 | 24,826 | 640 | 31 | 1,445 |
| v3.1.x | 2019 | 575 | 124,452 | 491 | 101,459 | 52 | 19,828 | 543 | 19 | 2,130 |
| v1.0.x | 2016 | 373 | 78,116 | 320 | 64,215 | 37 | 13,675 | 357 | 20 | 777 |

## Copyrights

| Holder | File Count | Files |
| --- | ---: | --- |
| Andrew Resch <andrewresch@gmail.com> | 1 | [xpra/net/rencodeplus/rencodeplus.pyx](xpra/net/rencodeplus/rencodeplus.pyx) |
| Antoine Martin <antoine@xpra.org> | 1,012 |  |
| Arthur Huillet | 2 | [xpra/codecs/csc_cython/converter.pyx](xpra/codecs/csc_cython/converter.pyx), [xpra/codecs/libyuv/converter.pyx](xpra/codecs/libyuv/converter.pyx) |
| Chris Marchetti <adamnew123456@gmail.com> | 1 | [xpra/platform/posix/proc.py](xpra/platform/posix/proc.py) |
| Daniel Woodhouse | 1 | [xpra/gtk/notifier.py](xpra/gtk/notifier.py) |
| eryksun | 1 | [xpra/platform/win32/printer_notify.py](xpra/platform/win32/printer_notify.py) |
| Jeremy Lainé | 1 | [xpra/net/quic/session_ticket_store.py](xpra/net/quic/session_ticket_store.py) |
| Joel Martin | 1 | [xpra/net/websockets/header.py](xpra/net/websockets/header.py) |
| Markus Pointner | 1 | [xpra/util/colorstreamhandler.py](xpra/util/colorstreamhandler.py) |
| Microsoft Corporation. All rights reserved | 1 | [xpra/platform/win32/setappid.cpp](xpra/platform/win32/setappid.cpp) |
| mjharkin | 2 | [xpra/net/websockets/headers/browser_cookie.py](xpra/net/websockets/headers/browser_cookie.py), [xpra/net/websockets/headers/env_cookie.py](xpra/net/websockets/headers/env_cookie.py) |
| Nathalie Casati <nat@yuka.ch> | 1 | [xpra/auth/keycloak.py](xpra/auth/keycloak.py) |
| Nathaniel McCallum <nathaniel@natemccallum.com> | 1 | [xpra/net/libproxy.py](xpra/net/libproxy.py) |
| Nathaniel Smith <njs@pobox.com> | 157 |  |
| Netflix, Inc | 29 |  |
| Pierre Ossman | 1 | [xpra/net/websockets/header.py](xpra/net/websockets/header.py) |
| Richard Outerbridge | 1 | [xpra/net/rfb/d3des.py](xpra/net/rfb/d3des.py) |
| Serviware (Arthur Huillet, <ahuillet@serviware.com>) | 35 |  |
| Yann Collet | 1 | [xpra/buffers/xxh3.h](xpra/buffers/xxh3.h) |
| Yusuke Shinyama | 1 | [xpra/net/rfb/d3des.py](xpra/net/rfb/d3des.py) |


---

# Quality

# Sonarqube:
![Sonarqube](./sonarqube-overview.png)
Updated 2025-08-13

The code coverage is not currently recorded by sonarqube.

## Github Workflows

The [unit tests](https://github.com/Xpra-org/xpra/tree/master/tests/unittests)
are run with every `git push` via [`test.yml`](https://github.com/Xpra-org/xpra/blob/master/.github/workflows/test.yml).

The source code is also compiled with [extra cythonization](https://github.com/Xpra-org/xpra/issues/3978)
which takes advantage of type hints to verify stronger type safety.


## Other linters used

* `pycharm` builtin linter, during development
* `ruff` via a [git pre-commit hook](https://github.com/Xpra-org/xpra/blob/master/.pre-commit-config.yaml)
