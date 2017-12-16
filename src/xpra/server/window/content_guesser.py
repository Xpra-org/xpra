# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("window", "util")

ROLE_MAP = {
    "text"      : ("gimp-dock", "gimp-toolbox", ),
    "picture"   : ("gimp-image-window", ),
    "browser"   : ("browser", ),
    }

RES_NAME = {
    "text"      : ("xterm", "terminal", "Eclipse", "gedit", "Mail", ),
    "video"     : ("vlc", ),
    "browser"   : ("google-chrome", "Navigator", "VirtualBox Manager", "chromium-browser", ),
    "picture"   : ("gimp", "VirtualBox Machine"),
    }
RES_CLASS = {
    "browser"   : ("Firefox", "Thunderbird", ),
    }


def match_map(value, ctmap):
    for content_type, values in ctmap.items():
        if any(value.find(x)>=0 for x in values):
            return content_type
    return None

def guess_content_type(window):
    role = window.get("role")
    if role:
        v = match_map(role, ROLE_MAP)
        if v:
            return v
    ci = window.get("class-instance")
    if not ci or len(ci)!=2:
        return ""
    res_name, res_class = ci
    v = None
    if res_name:
        v = match_map(res_name, RES_NAME)
    if res_class and not v:
        v = match_map(res_class, RES_CLASS)
    return v or ""
