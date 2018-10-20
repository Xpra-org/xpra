# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2017-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import re
import os.path
from xpra.os_util import load_binary_file, hexstr, PYTHON2, OSX, POSIX, LINUX
from collections import OrderedDict
from xpra.platform.paths import get_app_dir, get_user_conf_dirs

from xpra.log import Logger
log = Logger("window", "util")

DEFAULT_CONTENT_TYPE = os.environ.get("XPRA_DEFAULT_CONTENT_TYPE", "")


def get_proc_cmdline(pid):
    if pid and LINUX:
        #try to find the command via /proc:
        proc_cmd_line = os.path.join("/proc", "%s" % pid, "cmdline")
        if os.path.exists(proc_cmd_line):
            return load_binary_file(proc_cmd_line).rstrip("\0")
    return None

def getprop(window, prop):
    try:
        if prop not in window.get_property_names():
            log("no '%s' property on window %s", prop, window)
            return None
        return window.get_property(prop)
    except TypeError:
        log.error("Error querying %s on %s", name, window, exc_info=True)


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
            #ie: "title:helloworld=text   #some comments here" -> "title:helloworld", "text   #some comments here"
            if len(parts)!=2:
                log.warn("Warning: invalid content-type definition")
                log.warn(" found in '%s' at line %i", line, l)
                log.warn(" '%s' is missing a '='", line)
                continue
            match, content_type = parts
            parts = match.split(":", 1)
            #ie: "title:helloworld" -> "title", "helloworld"
            if len(parts)!=2:
                log.warn("Warning: invalid content-type definition")
                log.warn(" match string '%s' is missing a ':'", match)
                continue
            #ignore comments:
            #"text    #some comments here" > "text"
            content_type = content_type.split(":")[0].strip()
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


def guess_content_type_from_defs(window):
    global content_type_defs
    load_content_type_defs()
    for prop_name, defs in content_type_defs.items():
        if prop_name not in window.get_property_names():
            continue
        prop_value = window.get_property(prop_name)
        #special case for "command":
        #we can look it up using proc on Linux
        if not prop_value and prop_name=="command":
            pid = getprop(window, "pid")
            prop_value = get_proc_cmdline(pid)
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
    return None

def load_categories_to_type():
    d = os.path.join(get_app_dir(), "content-categories")
    if not os.path.exists(d) or not os.path.isdir(d):
        log("load_categories_to_type() directory '%s' not found", d)
        return {}
    categories_to_type = {}
    for f in sorted(os.listdir(d)):
        if f.endswith(".conf"):
            cc_file = os.path.join(d, f)
            if os.path.isfile(cc_file):
                try:
                    categories_to_type.update(load_content_categories_file(cc_file))
                except Exception as e:
                    log("load_content_type_file(%s)", cc_file, exc_info=True)
                    log.error("Error loading content-type data from '%s'", cc_file)
                    log.error(" %s", e)
    log("load_categories_to_type()=%s", categories_to_type)
    return categories_to_type
def load_content_categories_file(cc_file):
    if PYTHON2:
        mode = "rU"
    else:
        mode = "r"
    d = {}
    with open(cc_file, mode) as f:
        l = 0
        for line in f:
            l += 1
            line = line.rstrip("\n\r")
            if line.startswith("#") or not (line.strip()):
                continue
            parts = line.rsplit(":", 1)
            #ie: "title:helloworld=text   #some comments here" -> "title:helloworld", "text   #some comments here"
            if len(parts)!=2:
                log.warn("Warning: invalid content-type definition")
                log.warn(" found in '%s' at line %i", line, l)
                log.warn(" '%s' is missing a '='", line)
                continue
            category, content_type = parts
            d[category.strip("\t ").lower()] = content_type.strip("\t ")
    log("load_content_categories_file(%s)=%s", cc_file, d)
    return d  

command_to_type = None
def load_command_to_type():
    global command_to_type
    if command_to_type is None:
        command_to_type = {}
        from xpra.platform.xposix.xdg_helper import load_xdg_menu_data
        xdg_menu = load_xdg_menu_data()
        categories_to_type = load_categories_to_type()
        log("load_command_to_type() xdg_menu=%s, categories_to_type=%s", xdg_menu, categories_to_type) 
        if xdg_menu and categories_to_type:
            for category, entries in xdg_menu.items():
                log("category %s: %s", category, entries)
                for name, props in entries.items():
                    command = props.get("TryExec") or props.get("Exec")
                    categories = props.get("Categories")
                    log("Entry '%s': command=%s, categories=%s", name, command, categories)
                    if command and categories:
                        for c in categories:
                            ctype = categories_to_type.get(c.lower())
                            if not ctype:
                                #try a more fuzzy match:
                                for category,ct in categories_to_type.items():
                                    if c.lower().find(category)>=0:
                                        ctype = ct
                                        break
                            if ctype:
                                cmd = os.path.basename(command.split(" ")[0]).encode()
                                if cmd:
                                    command_to_type[cmd] = ctype
                                    break
        log("load_command_to_type()=%s", command_to_type)
    return command_to_type

def guess_content_type_from_command(window):
    if POSIX and not OSX:
        command = getprop(window, "command")
        if not command and LINUX:
            pid = getprop(window, "pid")
            command = get_proc_cmdline(pid)
        log("guess_content_type_from_command(%s) command=%s", window, command)
        if command:
            ctt = load_command_to_type()
            cmd = os.path.basename(command)
            ctype = ctt.get(cmd)
            log("content-type(%s)=%s", cmd, ctype)
            return ctype
    return None 


def guess_content_type(window):
    return guess_content_type_from_defs(window) or guess_content_type_from_command(window) or DEFAULT_CONTENT_TYPE
