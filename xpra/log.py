# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import sys
import logging
import weakref
import itertools

from typing import Any, Final
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
# This module is used by non-GUI programs and thus must not import gtk.

LOG_PREFIX: str = ""
LOG_FORMAT: str = "%(asctime)s %(message)s"
DEBUG_MODULES: Sequence[str] = ()
if os.name != "posix" or os.getuid() != 0:
    LOG_FORMAT = os.environ.get("XPRA_LOG_FORMAT", LOG_FORMAT)
    LOG_PREFIX = os.environ.get("XPRA_LOG_PREFIX", LOG_PREFIX)
    DEBUG_MODULES = tuple(x.strip() for x in os.environ.get("XPRA_DEBUG_MODULES", "").split(",") if x.strip())
NOPREFIX_FORMAT: Final[str] = "%(message)s"
EMOJIS = os.environ.get("XPRA_EMOJIS", "1") == "1"


BACKTRACE_LEVEL = int(os.environ.get("XPRA_LOG_BACKTRACE_LEVEL", logging.CRITICAL))
BACKTRACE_REGEXES: Sequence[str] = tuple(
    x for x in os.environ.get("XPRA_LOG_BACKTRACE_REGEXES", "").split("|") if x
)
DEBUG_REGEXES: Sequence[str] = tuple(
    x for x in os.environ.get("XPRA_DEBUG_REGEXES", "").split("|") if x
)


logging.basicConfig(format=LOG_FORMAT)
logging.root.setLevel(logging.INFO)

debug_enabled_categories: set[str] = set()
debug_disabled_categories: set[str] = set()
backtrace_expressions: set[re.Pattern] = set()
debug_expressions: set[re.Pattern] = set()
emojis = False


MODULE_FILE = os.path.join(os.sep, "xpra", "log.py")        # ie: "/xpra/log.py"


def get_debug_args() -> Sequence[str]:
    args: list[str] = []
    if debug_enabled_categories:
        args += list(debug_enabled_categories)
    if debug_disabled_categories:
        for x in debug_disabled_categories:
            args.append(f"-{x}")
    return args


class FullDebugContext:
    __slots__ = ("debug_enabled_categories", "enabled")

    def __enter__(self):
        self.debug_enabled_categories = debug_enabled_categories
        debug_enabled_categories.clear()
        debug_enabled_categories.add("all")
        self.enabled = []
        for x in get_all_loggers():
            if not x.is_debug_enabled():
                self.enabled.append(x)
                x.enable_debug()

    def __exit__(self, *_args):
        for x in self.enabled:
            x.disable_debug()
        debug_enabled_categories.clear()
        debug_enabled_categories.update(self.debug_enabled_categories)


def add_debug_category(*cat: str) -> None:
    remove_disabled_category(*cat)
    for c in cat:
        debug_enabled_categories.add(ALIASES.get(c, c))


def remove_debug_category(*cat: str) -> None:
    for c in cat:
        c = ALIASES.get(c, c)
        if c in debug_enabled_categories:
            debug_enabled_categories.remove(c)


def is_debug_enabled(cat: str) -> bool:
    if "all" in debug_enabled_categories:
        return True
    if cat in debug_enabled_categories:
        return True
    return isenvdebug(cat) or isenvdebug("ALL")


def add_disabled_category(*cat: str) -> None:
    remove_debug_category(*cat)
    for c in cat:
        debug_disabled_categories.add(ALIASES.get(c, c))


def remove_disabled_category(*cat: str) -> None:
    for c in cat:
        if c in debug_disabled_categories:
            debug_disabled_categories.remove(ALIASES.get(c, c))


def add_backtrace(*expressions: str) -> None:
    for e in expressions:
        backtrace_expressions.add(re.compile(e))


def remove_backtrace(*expressions: str) -> None:
    for e in expressions:
        try:
            backtrace_expressions.remove(re.compile(e))
        except KeyError:
            pass


def add_debug_expression(*expressions: str) -> None:
    for e in expressions:
        debug_expressions.add(re.compile(e))


def remove_debug_expression(*expressions: str) -> None:
    for e in expressions:
        try:
            debug_expressions.remove(re.compile(e))
        except KeyError:
            pass


add_backtrace(*BACKTRACE_REGEXES)
add_debug_expression(*DEBUG_REGEXES)


default_level: int = logging.DEBUG


def set_default_level(level: int) -> None:
    global default_level
    default_level = level


def standard_logging(log, level: int, msg: str, *args, **kwargs) -> None:
    # this function just delegates to the regular python stdlib logging `log`:
    kwargs.pop("remote", None)
    log(level, msg, *args, **kwargs)


# this allows us to capture all logging and redirect it:
# the default 'standard_logging' uses the logger,
# but the client may inject its own handler here
global_logging_handler: Callable = standard_logging


def set_global_logging_handler(h: Callable) -> Callable:
    assert callable(h)
    global global_logging_handler
    saved = global_logging_handler
    global_logging_handler = h
    return saved


def setloghandler(lh) -> None:
    logging.root.handlers = []
    logging.root.addHandler(lh)


def enable_color(to=sys.stdout, format_string=NOPREFIX_FORMAT) -> None:
    if not hasattr(to, "fileno") or not hasattr(to, "buffer"):
        # on win32 sys.stdout can be a "Blackhole",
        # which does not have a fileno
        return
    # pylint: disable=import-outside-toplevel
    import codecs
    to = codecs.getwriter("utf-8")(to.buffer, "replace")
    try:
        from xpra.util.colorstreamhandler import ColorStreamHandler
    except ImportError:
        pass
    else:
        csh = ColorStreamHandler(to)
        csh.setFormatter(logging.Formatter(format_string))
        setloghandler(csh)
        if EMOJIS:
            global emojis
            emojis = True


def enable_format(format_string: str) -> None:
    try:
        logging.root.handlers[0].formatter = logging.Formatter(format_string)
    except (AttributeError, IndexError):
        pass


def consume_verbose_argv(argv: list[str], *categories: str) -> bool:
    verbose = False
    for x in list(argv):
        if x in ("-v", "--verbose"):
            verbose = True
            argv.remove(x)
            for category in categories:
                add_debug_category(category)
                enable_debug_for(category)
    return verbose


# makes it easier to rename logging categories
# without having to modify older versions of the wiki and documentation
ALIASES: dict[str, str] = {
    "glib": "gtk",
    "event": "events",
    "filter": "filters",
    "mouse": "pointer",
    "statistics": "stats",
    "print": "printing",
    "display": "screen",
    "macos": "osx",
}

# noinspection PyPep8
STRUCT_KNOWN_FILTERS: dict[str, dict[str, str]] = {
    "Client": {
        "client"        : "All client code",
        "paint"         : "Client window paint code",
        "draw"          : "Client draw packets",
        "cairo"         : "Cairo paint code used with the GTK3 client",
        "opengl"        : "Client OpenGL rendering",
        "info"          : "About and Session info dialogs",
        "launcher"      : "The client launcher program",
    },
    "General": {
        "clipboard"     : "All clipboard operations",
        "notify"        : "Notification forwarding",
        "tray"          : "System Tray forwarding",
        "printing"      : "Printing",
        "file"          : "File transfers",
        "keyboard"      : "Keyboard mapping and key event handling",
        "ibus"          : "IBus keyboard layouts",
        "screen"        : "Screen and workarea dimension",
        "fps"           : "Frames per second",
        "xsettings"     : "XSettings synchronization",
        "dbus"          : "DBUS calls",
        "menu"          : "Menus",
        "events"        : "System and window events",
        "splash"        : "Splash screen",
    },
    "Window": {
        "window"        : "All window code",
        "damage"        : "Window X11 repaint events",
        "present"       : "Window X11 present events",
        "geometry"      : "Window geometry",
        "shape"         : "Window shape forwarding (XShape)",
        "focus"         : "Window focus",
        "workspace"     : "Window workspace synchronization",
        "metadata"      : "Window metadata",
        "alpha"         : "Window Alpha channel (transparency)",
        "state"         : "Window state",
        "icon"          : "Window icons",
        "frame"         : "Window frame",
        "grab"          : "Window grabs (both keyboard and mouse)",
        "dragndrop"     : "Window drag-n-drop events",
        "filters"       : "Window filters",
        "bell"          : "Bell events",
    },
    "Encoding": {
        "codec"         : "Codec loader and video helper",
        "loader"        : "Pixel compression codec loader",
        "video"         : "Video encoding",
        "score"         : "Video pipeline scoring and selection",
        "encoding"      : "Server side encoding selection and compression",
        "scaling"       : "Picture scaling",
        "scroll"        : "Scrolling detection and compression",
        "subregion"     : "Video subregion processing",
        "regiondetect"  : "Video region detection",
        "regionrefresh" : "Video region refresh",
        "refresh"       : "Refresh of lossy screen updates",
        "compress"      : "Pixel compression",
    },
    "Codec": {
        "csc"           : "Colourspace conversion codecs",
        "cuda"          : "CUDA device access",
        "cython"        : "Cython CSC module",
        "libyuv"        : "libyuv CSC module",
        "decoder"       : "All decoders",
        "encoder"       : "All encoders",
        "argb"          : "ARGB encoder",
        "pillow"        : "Pillow encoder and decoder",
        "spng"          : "spng codec",
        "jpeg"          : "JPEG codec",
        "vpx"           : "libvpx encoder and decoder",
        "amf"           : "amf encoder",
        "nvjpeg"        : "nvidia nvjpeg hardware encoder",
        "nvenc"         : "nvidia nvenc video hardware encoder",
        "nvdec"         : "nvidia nvdec video hardware decoder",
        "nvfbc"         : "nvidia nvfbc screen capture",
        "x264"          : "libx264 encoder",
        "openh264"      : "openh264 decoder",
        "aom"           : "aom codec",
        "webp"          : "libwebp encoder and decoder",
        "avif"          : "libavif encoder and decoder",
        "webcam"        : "webcam access",
        "evdi"          : "evdi virtual monitor",
        "drm"           : "direct rendering manager",
        "remote"        : "remote server codec",
    },
    "Pointer": {
        "pointer"       : "Pointer motion",
        "cursor"        : "Pointer cursor shape",
    },
    "Misc": {
        # libraries
        "gtk"           : "All GTK code: bindings, client, etc",
        "util"          : "All utility functions",
        "gobject"       : "Command line clients",
        "brotli"        : "Brotli bindings",
        "lz4"           : "LZ4 bindings",
        # server bits:
        "test"          : "Test code",
        "verbose"       : "Very verbose flag",
        # specific applications:
    },
    "Network": {
        # internal / network:
        "network"       : "All network code",
        "bandwidth"     : "Bandwidth detection and management",
        "ssh"           : "SSH connections",
        "ssl"           : "SSL connections",
        "http"          : "HTTP requests",
        "rtc"           : "RTC requests",
        "rfb"           : "RFB Protocol",
        "mmap"          : "mmap transfers",
        "protocol"      : "Packet input and output (formatting, parsing, sending and receiving)",
        "websocket"     : "WebSocket layer",
        "named-pipe"    : "Named pipe",
        "crypto"        : "Encryption",
        "auth"          : "Authentication",
        "upnp"          : "UPnP",
        "asyncio"       : "asyncio",
        "quic"          : "QUIC",
        "ping"          : "ping",
    },
    "Server": {
        "server"        : "All server code",
        "proxy"         : "Proxy server",
        "shadow"        : "Shadow server",
        "command"       : "Server control channel",
        "timeout"       : "Server timeouts",
        "exec"          : "Executing commands",
        # server features:
        "mdns"          : "mDNS session publishing",
        # server internals:
        "stats"         : "Server statistics",
        "xshm"          : "XShm pixel capture",
    },
    "Audio": {
        "audio"         : "All audio",
        "gstreamer"     : "GStreamer internal messages",
        "pulseaudio"    : "Pulseaudio configuration",
        "av-sync"       : "Audio-video sync",
    },
    "X11": {
        "x11"           : "All X11 code",
        "xinput"        : "XInput bindings",
        "bindings"      : "X11 Cython bindings",
        "core"          : "X11 core bindings",
        "randr"         : "X11 RandR bindings",
        "record"        : "X11 Record bindings",
        "ximage"        : "X11 XImage bindings",
        "composite"     : "X11 Composite bindings",
        "fixes"         : "X11 Fixes extension",
        "error"         : "X11 errors",
    },
    "Platform": {
        "platform"      : "All platforms",
        "import"        : "Platform support import",
        "osx"           : "Mac OS X platform",
        "win32"         : "Microsoft Windows platform",
        "posix"         : "Posix platform",
        "d3d11"         : "Microsoft Direct 3D 11",
        "wayland"       : "Wayland",
    },
}

# flatten it:
KNOWN_GROUPS: Sequence[str] = tuple(STRUCT_KNOWN_FILTERS.keys())
CATEGORY_GROUP: dict[str, str] = {}     # ie: {"posix": "Platform", ..}
CATEGORY_INFO: dict[str, str] = {}      # ie: {"posix": "Posix platform code", "compress": ...}
KNOWN_FILTERS: list[str] = []           # ie: ["posix", "compress", "x11", ...]
for group, d in STRUCT_KNOWN_FILTERS.items():
    KNOWN_FILTERS += list(d.keys())
    CATEGORY_INFO.update(d)
    for category in d.keys():
        CATEGORY_GROUP[category] = group
RESTRICTED_DEBUG_CATEGORIES = ("verbose", "network", "crypto", "auth", "keyboard")


def isenvdebug(category: str) -> bool:
    return os.environ.get("XPRA_%s_DEBUG" % category.upper().replace("-", "_").replace("+", "_"), "0") == "1"


def get_info() -> dict[str, Any]:
    info = {
        "categories": {
            "enabled": tuple(debug_enabled_categories),
            "disabled": tuple(debug_disabled_categories),
        },
        "backtrace-level": BACKTRACE_LEVEL,
        "backtrace-expressions": tuple(bt.pattern for bt in backtrace_expressions),
        "debug-expressions": tuple(bt.pattern for bt in debug_expressions),
        "handler": getattr(global_logging_handler, "__name__", "<unknown>"),
        "prefix": LOG_PREFIX,
        "format": LOG_FORMAT,
        "debug-modules": DEBUG_MODULES,
    }
    from xpra.common import FULL_INFO
    if FULL_INFO > 1:
        info["filters"] = STRUCT_KNOWN_FILTERS
    return info


class Logger:
    """
    A wrapper around 'logging' with some convenience stuff.  In particular:
    * You initialize it with a list of categories
        If unset, the default logging target is set to the name of the module where
        Logger() was called.
    * Any of the categories can enable debug logging if the environment
    variable 'XPRA_${CATEGORY}_DEBUG' is set to "1"
    * We also keep a list of debug_categories, so these can get enabled
        programmatically too
    * We keep track of which loggers are associated with each category,
        so we can enable/disable debug logging by category
    * You can pass exc_info=True to any method, and sys.exc_info() will be
        substituted.
    * __call__ is an alias for debug
    * we bypass the logging system unless debugging is enabled for the logger,
        which is much faster than relying on the python logging code
    """
    __slots__ = ("categories",
                 "level", "level_override", "min_level", "_logger", "debug_enabled", "__weakref__", "debug")

    def __init__(self, *categories: str):
        self.debug = self.__call__
        self.min_level = 0
        self.categories = list(ALIASES.get(category, category) for category in categories)
        n = 1
        caller = ""
        while n < 10:
            try:
                # noinspection PyProtectedMember
                caller = sys._getframe(n).f_globals["__name__"]  # pylint: disable=protected-access
                if caller == "__main__" or caller.startswith("importlib"):
                    n += 1
                else:
                    break
            except (AttributeError, ValueError):
                break
        if caller and caller != "__main__" and not caller.startswith("importlib"):
            self.categories.insert(0, caller)
        self.level = logging.INFO
        self.level_override = 0
        self._logger = logging.getLogger(".".join(self.categories))
        self.setLevel(default_level)
        disabled = False
        enabled = False
        if caller in DEBUG_MODULES:
            enabled = True
        else:
            for cat in self.categories:
                if cat in debug_disabled_categories:
                    disabled = True
                if is_debug_enabled(cat):
                    enabled = True
            if len(categories) > 1:
                # try all string permutations of those categories:
                # "keyboard", "events" -> "keyboard+events" or "events+keyboard"
                for cats in itertools.permutations(categories):
                    cstr = "+".join(cats)
                    if cstr in debug_disabled_categories:
                        disabled = True
                    if is_debug_enabled(cstr):
                        enabled = True
        self.debug_enabled = enabled and not disabled
        # ready, keep track of it:
        add_logger(self.categories, self)
        for x in categories:
            if ALIASES.get(x, x) not in KNOWN_FILTERS:
                self.warn("unknown logging category: %s", x)
        if self.debug_enabled:
            self.debug(f"debug enabled for {self.categories}")

    def get_info(self) -> dict[str, Any]:
        return {
            "categories": self.categories,
            "debug": self.debug_enabled,
            "level": self._logger.getEffectiveLevel(),
        }

    def __repr__(self):
        return f"Logger{self.categories}"

    def getEffectiveLevel(self) -> int:
        return self._logger.getEffectiveLevel()

    def setLevel(self, level: int) -> None:
        self.level = level
        self._logger.setLevel(level)

    def is_debug_enabled(self) -> bool:
        return self.debug_enabled

    def enable_debug(self) -> None:
        self.debug_enabled = True

    def disable_debug(self) -> None:
        self.debug_enabled = False

    def critical(self, enable=False) -> None:
        self.level_override = logging.CRITICAL if enable else 0

    def log(self, level: int, msg: str, *args, **kwargs) -> None:
        level_override = self.level_override or level
        if level_override <= self.min_level:
            if any(exp.match(msg) for exp in debug_expressions):
                level_override = logging.INFO
            else:
                return
        exc_info = kwargs.get("exc_info", None)
        # noinspection PySimplifyBooleanCheck
        if exc_info is True:
            kwargs.pop("exc_info")
            ei = sys.exc_info()
            if ei != (None, None, None):
                kwargs["exc_info"] = ei
        if LOG_PREFIX:
            msg = LOG_PREFIX + msg
        frame = kwargs.pop("frame", None)
        backtrace = kwargs.pop("backtrace", level >= BACKTRACE_LEVEL) or bool(frame)
        if backtrace or any(exp.match(msg) for exp in backtrace_expressions):
            import traceback
            tb = traceback.extract_stack(frame)
            count = len(tb)
            for i, frame in enumerate(tb):
                if frame.filename.endswith(MODULE_FILE) and i >= (count - 3):
                    # skip the logger's own calls
                    break
                try:
                    frame_summary = tb.format_frame_summary(frame)
                except AttributeError:
                    # `format_frame_summary` requires Python 3.11
                    pass
                else:
                    for rec in frame_summary.splitlines():
                        global_logging_handler(self._logger.log, level_override, rec)
        global_logging_handler(self._logger.log, level_override or level, msg, *args, **kwargs)

    def __call__(self, msg: str, *args, **kwargs) -> None:
        if self.debug_enabled or (debug_expressions and any(exp.match(msg) for exp in debug_expressions)):
            self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self.log(logging.INFO, msg, *args, **kwargs)

    def warn(self, msg: str, *args, **kwargs) -> None:
        if emojis:
            if msg.startswith("Warning:"):
                msg = "⚠️  " + msg[len("Warning:"):].strip()
            elif msg.startswith(" "):
                msg = "   " + msg.strip()
        self.log(logging.WARN, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        if emojis:
            if msg.startswith("Error:"):
                msg = "🔴 " + msg[len("Error:"):].strip()
            elif msg.startswith(" "):
                msg = "   " + msg.strip()
        self.log(logging.ERROR, msg, *args, **kwargs)

    def estr(self, e, **kwargs) -> None:
        einfo = str(e) or type(e)
        self.error(f" {einfo}", **kwargs)

    def handle(self, record) -> None:
        self.log(record.levelno, record.msg, *record.args, exc_info=record.exc_info)

    def trap_error(self, message: str, *args) -> AbstractContextManager:
        return ErrorTrapper(self, message, args)


class ErrorTrapper(AbstractContextManager):
    def __init__(self, logger, message, args):
        self.logger = logger
        self.message = message
        self.args = args

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type:
            self.logger.error(self.message, *self.args, exc_info=(exc_type, exc_val, exc_tb), backtrace=True)
            return True
        return False

    def __repr__(self):
        return "ErrorTrapper"


# we want to keep a reference to all the loggers in use,
# and we may have multiple loggers for the same key,
# but we don't want to prevent garbage collection so use a list of `weakref`s
all_loggers: dict[str, set['weakref.ReferenceType[Logger]']] = {}


def add_logger(categories: Sequence[str], logger: Logger) -> None:
    categories = list(categories)
    categories.append("all")
    ref_logger = weakref.ref(logger)
    for cat in categories:
        all_loggers.setdefault(cat, set()).add(ref_logger)


def get_all_loggers() -> set[Logger]:
    a = set()
    for loggers_set in all_loggers.values():
        for logger in tuple(loggers_set):
            # weakref:
            instance = logger()
            if instance:
                a.add(instance)
    return a


def get_loggers_for_categories(*categories: str) -> list[Logger]:
    if not categories or (len(categories) == 1 and categories[0] in ("none", "")):
        return []
    if "all" in categories:
        return list(get_all_loggers())
    cset = set(ALIASES.get(cat, cat) for cat in categories)
    matches = set()
    for logger in get_all_loggers():
        if set(logger.categories).issuperset(cset):
            matches.add(logger)
    return list(matches)


def enable_debug_for(*cat: str) -> list[Logger]:
    loggers: list[Logger] = []
    for logger in get_loggers_for_categories(*cat):
        if not logger.is_debug_enabled():
            logger.enable_debug()
            loggers.append(logger)
    return loggers


def disable_debug_for(*cat: str) -> list[Logger]:
    loggers: list[Logger] = []
    for logger in get_loggers_for_categories(*cat):
        if logger.is_debug_enabled():
            logger.disable_debug()
            loggers.append(logger)
    return loggers


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def handle(self, record) -> None:
        self.records.append(record)

    def emit(self, record) -> None:
        self.records.append(record)

    def createLock(self) -> None:
        self.lock = None


class SIGPIPEStreamHandler(logging.StreamHandler):
    def flush(self) -> None:
        try:
            super().flush()
        except BrokenPipeError:
            pass

    def emit(self, record) -> None:
        # noinspection PyBroadException
        try:
            msg = self.format(record)
            stream = self.stream
            # issue 35046: merged two stream.writes into one.
            stream.write(msg + self.terminator)
            self.flush()
        except RecursionError:  # See issue 36272
            raise
        except BrokenPipeError:
            pass
        except Exception:
            self.handleError(record)
