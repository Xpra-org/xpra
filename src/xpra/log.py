# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import logging
import weakref
# This module is used by non-GUI programs and thus must not import gtk.

LOG_PREFIX = os.environ.get("XPRA_LOG_PREFIX", "")
LOG_FORMAT = os.environ.get("XPRA_LOG_FORMAT", "%(asctime)s %(message)s")
NOPREFIX_FORMAT = "%(message)s"

logging.basicConfig(format=LOG_FORMAT)
logging.root.setLevel(logging.INFO)

#so we can keep a reference to all the loggers in use
#we may have multiple loggers for the same key, so use a dict
#but we don't want to prevent garbage collection so use a list of weakrefs
all_loggers = dict()
def add_logger(categories, logger):
    global all_loggers
    categories = list(categories)
    categories.append("all")
    l = weakref.ref(logger)
    for cat in categories:
        all_loggers.setdefault(cat, set()).add(l)

def get_all_loggers():
    global all_loggers
    a = set()
    for loggers in all_loggers.values():
        for l in list(loggers):
            #weakref:
            v = l()
            if v:
                a.add(v)
    return a

debug_enabled_categories = set()
debug_disabled_categories = set()
def add_debug_category(*cat):
    remove_disabled_category(*cat)
    for c in cat:
        debug_enabled_categories.add(c)

def remove_debug_category(*cat):
    for c in cat:
        if c in debug_enabled_categories:
            debug_enabled_categories.remove(c)

def is_debug_enabled(category):
    if "all" in debug_enabled_categories:
        return True
    if category in debug_enabled_categories:
        return True
    return isenvdebug(category) or isenvdebug("ALL")


def add_disabled_category(*cat):
    remove_debug_category(*cat)
    for c in cat:
        debug_disabled_categories.add(c)

def remove_disabled_category(*cat):
    for c in cat:
        if c in debug_disabled_categories:
            debug_disabled_categories.remove(c)


def get_loggers_for_categories(*cat):
    if not cat:
        return  []
    if "all" in cat:
        return get_all_loggers()
    cset = set(cat)
    matches = set()
    for l in get_all_loggers():
        if set(l.categories).issuperset(cset):
            matches.add(l)
    return list(matches)

def enable_debug_for(*cat):
    loggers = get_loggers_for_categories(*cat)
    for l in loggers:
        if not l.is_debug_enabled():
            l.enable_debug()
    return loggers

def disable_debug_for(*cat):
    loggers = get_loggers_for_categories(*cat)
    for l in loggers:
        if l.is_debug_enabled():
            l.disable_debug()
    return loggers


default_level = logging.DEBUG
def set_default_level(level):
    global default_level
    default_level = level


def standard_logging(log, level, msg, *args, **kwargs):
    #this is just the regular logging:
    log(level, msg, *args, **kwargs)

#this allows us to capture all logging and redirect it:
#the default 'standard_logging' uses the logger,
#but the client may inject its own handler here
global_logging_handler = standard_logging

def set_global_logging_handler(h):
    global global_logging_handler
    saved = global_logging_handler
    global_logging_handler = h
    return saved


def setloghandler(lh):
    logging.root.handlers = []
    logging.root.addHandler(lh)

def enable_color(to=sys.stdout, format_string=NOPREFIX_FORMAT):
    if not hasattr(to, "fileno"):
        #on win32 sys.stdout can be a "Blackhole",
        #which does not have a fileno
        return
    from xpra.colorstreamhandler import ColorStreamHandler
    csh = ColorStreamHandler(to)
    csh.setFormatter(logging.Formatter(format_string))
    setloghandler(csh)

def enable_format(format_string):
    try:
        logging.root.handlers[0].formatter = logging.Formatter(format_string)
    except:
        pass


from collections import OrderedDict
STRUCT_KNOWN_FILTERS = OrderedDict([
    ("Client", OrderedDict([
                ("client"       , "All client code"),
                ("paint"        , "Client window paint code"),
                ("draw"         , "Client draw packets"),
                ("cairo"        , "Cairo paint code used with the GTK3 client"),
                ("opengl"       , "Client OpenGL rendering"),
                ("info"         , "About and Session info dialogs"),
                ("launcher"     , "The client launcher program"),
                ])),
    ("General", OrderedDict([
                ("clipboard"    , "All clipboard operations"),
                ("notify"       , "Notification forwarding"),
                ("tray"         , "System Tray forwarding"),
                ("printing"     , "Printing"),
                ("file"         , "File transfers"),
                ("keyboard"     , "Keyboard mapping and key event handling"),
                ("screen"       , "Screen and workarea dimension"),
                ("fps"          , "Frames per second"),
                ("xsettings"    , "XSettings synchronization"),
                ("dbus"         , "DBUS calls"),
                ("rpc"          , "Remote Procedure Calls"),
                ("menu"         , "Menus"),
                ("events"       , "System and window events"),
                ])),
    ("Window", OrderedDict([
                ("window"       , "All window code"),
                ("damage"       , "Window X11 repaint events"),
                ("geometry"     , "Window geometry"),
                ("shape"        , "Window shape forwarding (XShape)"),
                ("focus"        , "Window focus"),
                ("workspace"    , "Window workspace synchronization"),
                ("metadata"     , "Window metadata"),
                ("state"        , "Window state"),
                ("icon"         , "Window icons"),
                ("frame"        , "Window frame")
                ])),
    ("Encoding", OrderedDict([
                ("codec"        , "Codec loader and video helper"),
                ("loader"       , "Pixel compression codec loader"),
                ("video"        , "Video encoding"),
                ("score"        , "Video pipeline scoring and selection"),
                ("encoding"     , "Server side encoding selection and compression"),
                ("scaling"      , "Picture scaling"),
                ("delta"        , "Delta pre-compression"),
                ("scroll"       , "Scrolling detection and compression"),
                ("xor"          , "XOR delta pre-compression"),
                ("subregion"    , "Video subregion processing"),
                ("regiondetect" , "Video region detection"),
                ("regionrefresh", "Video region refresh"),
                ("refresh"      , "Refresh of lossy screen updates"),
                ("compress"     , "Pixel compression (non video)"),
                ])),
    ("Codec", OrderedDict([
                #codecs:
                ("csc"          , "Colourspace conversion codecs"),
                ("cuda"         , "CUDA device access (nvenc)"),
                ("cython"       , "Cython CSC module"),
                ("swscale"      , "swscale CSC module"),
                ("libyuv"       , "libyuv CSC module"),
                ("decoder"      , "All decoders"),
                ("encoder"      , "All encoders"),
                ("avcodec"      , "avcodec decoder"),
                ("libav"        , "libav common code (used by swscale, avcodec and ffmpeg)"),
                ("ffmpeg"       , "ffmpeg encoder"),
                ("pillow"       , "Pillow encoder and decoder"),
                ("jpeg"         , "JPEG codec"),
                ("vpx"          , "libvpx encoder and decoder"),
                ("nvenc"        , "nvenc encoder (all versions)"),
                ("x264"         , "libx264 encoder"),
                ("x265"         , "libx265 encoder"),
                ("webcam"       , "webcam access"),
                ])),
    ("Pointer", OrderedDict([
                ("mouse"        , "Mouse motion"),
                ("cursor"       , "Mouse cursor shape"),
                ])),
    ("Misc", OrderedDict([
                #libraries
                ("gtk"          , "All GTK code: bindings, client, etc"),
                ("util"         , "All utility functions"),
                ("gobject"      , "Command line clients"),
                ("grab"         , "Window grabs (both keyboard and mouse)"),
                #server bits:
                ("test"         , "Test code"),
                ("verbose"      , "Very verbose flag"),
                #specific applications:
                ])),
    ("Network", OrderedDict([
                #internal / network:
                ("network"      , "All network code"),
                ("http"         , "HTTP requests"),
                ("mmap"         , "mmap transfers"),
                ("protocol"     , "Packet input and output (formatting, parsing, sending and receiving)"),
                ("websocket"    , "Websocket layer"),
                ("named-pipe"   , "Named pipe"),
                ("crypto"       , "Encryption"),
                ("auth"         , "Authentication"),
                ])),
    ("Server", OrderedDict([
                #Server:
                ("server"       , "All server code"),
                ("proxy"        , "Proxy server"),
                ("shadow"       , "Shadow server"),
                ("command"      , "Server control channel"),
                ("timeout"      , "Server timeouts"),
                ("exec"         , "Executing commands"),
                #server features:
                ("mdns"         , "mDNS session publishing"),
                #server internals:
                ("stats"        , "Server statistics"),
                ("xshm"         , "XShm pixel capture"),
                ])),
    ("Sound", OrderedDict([
                ("sound"        , "All sound"),
                ("gstreamer"    , "GStreamer internal messages"),
                ("av-sync"      , "Audio-video sync"),
                ])),
    ("X11", OrderedDict([
                ("x11"          , "All X11 code"),
                ("bindings"     , "X11 Cython bindings"),
                ("core"         , "X11 core bindings"),
                ("randr"        , "X11 RandR bindings"),
                ("ximage"       , "X11 XImage bindings"),
                ("error"        , "X11 errors"),
                ])),
    ("Platform", OrderedDict([
                ("platform"     , "All platform support code"),
                ("import"       , "Platform support import code"),
                ("osx"          , "Mac OS X platform support code"),
                ("win32"        , "Microsoft Windows platform support code"),
                ("posix"        , "Posix platform code"),
                ])),
    ])

#flatten it:
KNOWN_FILTERS = OrderedDict()
for category, d in STRUCT_KNOWN_FILTERS.items():
    for k,v in d.items():
        KNOWN_FILTERS[k] = v


def isenvdebug(category):
    return os.environ.get("XPRA_%s_DEBUG" % category.upper(), "0")=="1"

# A wrapper around 'logging' with some convenience stuff.  In particular:
#    -- You initialize it with a list of categories
#       If unset, the default logging target is set to the name of the module where
#       Logger() was called.
#    -- Any of the categories can enable debug logging if the environment
#       variable 'XPRA_${CATEGORY}_DEBUG' is set to "1"
#    -- We also keep a list of debug_categories, so these can get enabled
#       programatically too
#    -- We keep track of which loggers are associated with each category,
#       so we can enable/disable debug logging by category
#    -- You can pass exc_info=True to any method, and sys.exc_info() will be
#       substituted.
#    -- __call__ is an alias for debug
#    -- we bypass the logging system unless debugging is enabled for the logger,
#       which is much faster than relying on the python logging code

class Logger(object):
    def __init__(self, *categories):
        global default_level, debug_disabled_categories, KNOWN_FILTERS
        self.categories = list(categories)
        caller = sys._getframe(1).f_globals["__name__"]
        if caller!="__main__":
            self.categories.insert(0, caller)
        self.logger = logging.getLogger(".".join(self.categories))
        self.logger.setLevel(default_level)
        disabled = False
        enabled = False
        for cat in self.categories:
            if cat in debug_disabled_categories:
                disabled = True
            if is_debug_enabled(cat):
                enabled = True
        self.debug_enabled = enabled and not disabled
        #ready, keep track of it:
        add_logger(self.categories, self)
        for x in categories:
            if x not in KNOWN_FILTERS:
                self.warn("unknown logging category: %s", x)

    def get_info(self):
        return {
            "categories"    : self.categories,
            "debug"         : self.debug_enabled,
            "level"         : self.logger.getEffectiveLevel(),
            }

    def __repr__(self):
        return "Logger(%s)" % ", ".join(self.categories)

    def is_debug_enabled(self):
        return self.debug_enabled

    def enable_debug(self):
        self.debug_enabled = True

    def disable_debug(self):
        self.debug_enabled = False


    def log(self, level, msg, *args, **kwargs):
        if kwargs.get("exc_info") is True:
            kwargs["exc_info"] = sys.exc_info()
        global global_logging_handler
        if LOG_PREFIX:
            msg = LOG_PREFIX+msg
        global_logging_handler(self.logger.log, level, msg, *args, **kwargs)

    def __call__(self, msg, *args, **kwargs):
        if self.debug_enabled:
            self.log(logging.DEBUG, msg, *args, **kwargs)
    def debug(self, msg, *args, **kwargs):
        if self.debug_enabled:
            self.log(logging.DEBUG, msg, *args, **kwargs)
    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)
    def warn(self, msg, *args, **kwargs):
        self.log(logging.WARN, msg, *args, **kwargs)
    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)


class CaptureHandler(logging.Handler):

    def __init__(self):
        logging.Handler.__init__(self, logging.DEBUG)
        self.records = []

    def handle(self, record):
        self.records.append(record)

    def emit(self, record):
        self.records.append(record)

    def createLock(self):
        self.lock = None
