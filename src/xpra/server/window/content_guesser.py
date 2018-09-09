# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os.path
from xpra.os_util import PYTHON2
from collections import OrderedDict
from xpra.platform.paths import get_app_dir, get_user_conf_dirs

from xpra.log import Logger
log = Logger("window", "util")


content_type_defs = None
def load_content_type_defs():
    global content_type_defs
    if content_type_defs is None:
        content_type_defs = OrderedDict()
        content_type_dir = os.path.join(get_app_dir(), "content-type")
        log("load_content_type_defs() content_type_dir=%s", content_type_dir)
        load_content_type_dir(content_type_dir)
        for d in get_user_conf_dirs():
            load_content_type_dir(d)
    return content_type_defs

def load_content_type_dir(d):
    log("load_content_type_dir(%s)", d)
    if not os.path.exists(d) or not os.path.isdir(d):
        return
    for f in sorted(os.listdir(d)):
        if f.endswith(".conf"):
            ct_file = os.path.join(d, f)
            if os.path.isfile(ct_file):
                try:
                    load_content_type_file(ct_file)
                except Exception as e:
                    log("load_content_type_file(%s)", ct_file, exc_info=True)
                    log.error("Error loading content-type data from '%s'", ct_file)
                    log.error(" %s", e)

def load_content_type_file(ct_file):
    global content_type_defs
    if PYTHON2:
        mode = "rU"
    else:
        mode = "r"
    with open(ct_file, mode) as f:
        l = 0
        for line in f:
            l += 1
            line = line.rstrip("\n\r")
            if line.startswith("#") or not (line.strip()):
                continue
            parts = line.rsplit("=", 1)
            #ie: "title:helloworld=text" -> "title:helloworld", "text"
            if len(parts)!=2:
                log.warn("Warning: invalid content-type definition")
                log.warn(" found in '%s' at line %i", ct_file, l)
                log.warn(" '%s' is missing a '='", line)
                continue
            match, content_type = parts
            parts = match.split(":", 1)
            #ie: "title:helloworld" -> "title", "helloworld"
            if len(parts)!=2:
                log.warn("Warning: invalid content-type definition")
                log.warn(" match string '%s' is missing a ':'", match)
                continue
            prop_name, regex = parts
            try:
                c = re.compile(regex)
                content_type_defs.setdefault(prop_name, OrderedDict())[c]=(regex, content_type)
                log("%16s matching '%s' is %s", prop_name, regex, content_type)
            except Exception as e:
                log.warn("Warning: invalid regular expression")
                log.warn(" match string '%s':", regex)
                log.warn(" %s", e)
                continue


def get_content_type_properties():
    """ returns the list of window properties which can be used
        to guess the content-type.
    """
    load_content_type_defs()
    return content_type_defs.keys()


def guess_content_type(window):
    global content_type_defs
    load_content_type_defs()
    for prop_name, defs in content_type_defs.items():
        if prop_name not in window.get_property_names():
            continue
        prop_value = window.get_property(prop_name)
        #some properties return lists of values,
        #in which case we try to match any of them:
        if isinstance(prop_value, (list,tuple)):
            values = prop_value
        else:
            values = [prop_value]
        for value in values:
            for regex, match_data in defs.items():
                if regex.search(str(value)):
                    regex_str, content_type = match_data
                    log("guess_content_type(%s) found match: property=%s, regex=%s, content-type=%s", window, prop_name, regex_str, content_type)
                    return content_type
    return ""
