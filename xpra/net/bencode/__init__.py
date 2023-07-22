# This file is part of Xpra.
# Copyright (C) 2014-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=import-outside-toplevel
from typing import Tuple, Any, Callable

def init() -> Tuple[Callable[[Any],bytes],Callable[[bytes],Any],Tuple[Any,...]]:
    from xpra.util import envbool
    if envbool("XPRA_USE_CYTHON_BENCODE", True):
        try:
            from xpra.net.bencode import cython_bencode # type: ignore[attr-defined]
            return cython_bencode.bencode, cython_bencode.bdecode, cython_bencode.__version__
        except ImportError as e:
            from xpra.os_util import get_util_logger
            get_util_logger().warn("Warning: cannot load cython bencode module: %s", e)
    from xpra.net.bencode import python_bencode
    return python_bencode.bencode, python_bencode.bdecode, python_bencode.__version__


bencode, bdecode, __version__ = init()

__all__ = ['bencode', 'bdecode', "__version__"]
