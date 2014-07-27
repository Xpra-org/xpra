# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys

from xpra.log import Logger
log = Logger("network", "protocol")
debug = log.debug


rencode_dumps, rencode_loads, rencode_version = None, None, None
try:
    try:
        from xpra.net.rencode import dumps as rencode_dumps  #@UnresolvedImport
        from xpra.net.rencode import loads as rencode_loads  #@UnresolvedImport
        from xpra.net.rencode import __version__ as rencode_version
    except ImportError, e:
        log.warn("rencode import error: %s", e)
except Exception, e:
    log.error("error loading rencode", exc_info=True)
has_rencode = rencode_dumps is not None and rencode_loads is not None and rencode_version is not None
use_rencode = has_rencode and os.environ.get("XPRA_USE_RENCODER", "1")=="1"
log("packet encoding: has_rencode=%s, use_rencode=%s, version=%s", has_rencode, use_rencode, rencode_version)


bencode, bdecode, bencode_version = None, None, None
if sys.version_info[0]<3:
    #bencode needs porting to Python3..
    try:
        try:
            from xpra.net.bencode import bencode, bdecode, __version__ as bencode_version
        except ImportError, e:
            log.warn("bencode import error: %s", e, exc_info=True)
    except Exception, e:
        log.error("error loading bencoder", exc_info=True)
has_bencode = bencode is not None and bdecode is not None
use_bencode = has_bencode and os.environ.get("XPRA_USE_BENCODER", "1")=="1"
log("packet encoding: has_bencode=%s, use_bencode=%s, version=%s", has_bencode, use_bencode, bencode_version)


yaml_encode, yaml_decode, yaml_version = None, None, None
try:
    #json messes with strings and unicode (makes it unusable for us)
    import yaml
    yaml_encode = yaml.dump
    yaml_decode = yaml.load
    yaml_version = yaml.__version__
except ImportError:
    log("yaml not found")
has_yaml = yaml_encode is not None and yaml_decode is not None
use_yaml = has_yaml and os.environ.get("XPRA_USE_YAML", "1")=="1"
log("packet encoding: has_yaml=%s, use_yaml=%s, version=%s", has_yaml, use_yaml, yaml_version)
