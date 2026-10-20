# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import re
from io import BytesIO
from typing import TypeAlias
from collections.abc import Sequence

from xpra.os_util import gi_import, POSIX, OSX
from xpra.util.env import first_time, envint
from xpra.util.io import load_binary_file
from xpra.log import Logger

log = Logger("dbus", "notify")

IconData: TypeAlias = tuple[str, int, int, bytes]

SVG_SIZE = 96

ICON_EXTENSIONS = ("png", "xpm", )

BUS_NAME = "org.freedesktop.Notifications"
BUS_PATH = "/org/freedesktop/Notifications"
# the name our notification forwarder returns from `GetServerInformation`,
# used to detect that we would be talking to a forwarder - see `get_notification_service_name`:
PROXY_NAME = "xpra-notification-proxy"

# the icon encodings we are willing to decode from an untrusted peer:
ICON_ENCODINGS = ("png", "jpeg", "webp")
# larger than this is not an icon, it's a payload:
ICON_MAX_SIZE = envint("XPRA_NOTIFICATION_ICON_MAX_SIZE", 256)
# an icon name we can safely hand to the notification daemon, which looks it up in the icon theme:
# anything else (a path, or a URI like `file://`) would have the daemon load a local file
# through its own image loaders, bypassing `sanitize_icon_data`:
ICON_NAME_RE = re.compile(r"[A-Za-z0-9._+-]{1,128}")
# the body markup tags that make the notification daemon load a local file (`img`)
# or open a link (`a href`) - the text of a link is kept:
UNSAFE_MARKUP_RE = re.compile(r"<\s*/?\s*(img|a)\b[^>]*>", re.IGNORECASE)
# dbus uses a signed 32-bit integer, -1 means the notification daemon's default:
MAX_EXPIRE_TIMEOUT = 2**31 - 1
# control characters, except for line breaks and tabs:
TEXT_STRIP: dict[int, str | None] = dict.fromkeys(c for c in (*range(0x00, 0x20), *range(0x7f, 0xa0)) if chr(c) not in "\t\n")
# larger than this is not a notification:
MAX_APP_NAME = envint("XPRA_NOTIFICATION_MAX_APP_NAME", 64)
MAX_SUMMARY = envint("XPRA_NOTIFICATION_MAX_SUMMARY", 256)
MAX_BODY = envint("XPRA_NOTIFICATION_MAX_BODY", 4096)
# number of actions (key and label pairs):
MAX_ACTIONS = envint("XPRA_NOTIFICATION_MAX_ACTIONS", 8)
MAX_ACTION_KEY = 256
MAX_ACTION_LABEL = 64
# control characters, line separators and bidi controls,
# which can be used to hide or reverse the " (via Xpra)" suffix of the application name:
SINGLE_LINE_STRIP: dict[int, str | None] = dict.fromkeys((
    *range(0x00, 0x20), *range(0x7f, 0xa0),
    0x061c, 0x200e, 0x200f, *range(0x202a, 0x202f), *range(0x2066, 0x206a),
))
# line breaks and tabs become spaces:
SINGLE_LINE_STRIP |= dict.fromkeys(map(ord, "\t\n\v\f\r\x85\u2028\u2029"), " ")


def PIL_Image():
    try:
        # pylint: disable=import-outside-toplevel
        from PIL import Image
        return Image
    except ImportError:
        if first_time("parse-image-requires-pillow"):
            log.info("using notification icons requires python-pillow")
        return None


def parse_image_data(data) -> IconData | None:
    with log.trap_error("Error parsing icon data for notification"):
        width, height, rowstride, has_alpha, bpp, channels, pixels = data
        log("parse_image_data(%i, %i, %i, %s, %i, %i, %i bytes)",
            width, height, rowstride, bool(has_alpha), bpp, channels, len(pixels))
        Image = PIL_Image()
        if not Image:
            return None
        if channels == 4:
            rgb_format = "BGRA"
            fmt = "RGBA"
        elif channels == 3:
            rgb_format = "BGR"
            fmt = "RGB"
        else:
            raise ValueError(f"invalid number of channels: {channels}")
        if isinstance(pixels, (list, tuple)):
            pixels = bytes(pixels)
        img = Image.frombytes(fmt, (width, height), pixels, "raw", rgb_format, rowstride)
        if channels == 4 and not has_alpha:
            img = img.convert("RGB")
        return image_data(img)


def parse_image_path(path: str) -> IconData | None:
    log("parse_image_path(%s)", path)
    if path.startswith("file://"):
        path = path.removeprefix("file://")
    if not os.path.exists(path):
        log(" %r does not exist", path)
        return None
    Image = PIL_Image()
    if not Image:
        log(" cannot parse images without python-pillow")
        return None
    if path.endswith(".svg"):
        # note: this code path is currently unused,
        # because we don't include `svg` in `ICON_EXTENSIONS`
        # even if we did, `svg_to_png` requires GdkPixbuf,
        # which requires Gtk, which we do not want.
        from xpra.util.thread import is_main_thread
        if is_main_thread():
            try:
                from xpra.codecs.icon_util import svg_to_png
            except ImportError as e:
                log("cannot parse svg image %r: %s", path, e)
                return None
            svg_data = load_binary_file(path)
            png_data = svg_to_png(path, svg_data, SVG_SIZE, SVG_SIZE)
            if not png_data:
                log("svg_to_png failed")
                return None
            img = Image.open(BytesIO(png_data))
            return image_data(img)
        else:
            from threading import current_thread
            log.warn("Warning: cannot load SVG image %r", path)
            log.warn(" from %r thread", current_thread())
            log("parse_image_path(%s)", path, backtrace=True)
        return None
    try:
        img = Image.open(path)
        w, h = img.size
        maxsize = max(w, h)
        minsize = min(w, h)
        if maxsize > 100 or 0 < minsize < 48:
            img = img.resize((max(48, w * 100 // maxsize), max(48, h * 100 // maxsize)), Image.Resampling.BILINEAR)
        return image_data(img)
    except Exception as e:
        log(f"failed to open image {path!r}", exc_info=True)
        log.error("Error loading image for notification")
        log.error(f" using path {path!r}:")
        estr = str(e)
        if estr.endswith(f"{path!r}"):
            estr = estr[:-len(f"{path!r}")]
        log.error(f" {estr}")
    return None


def image_data(img) -> IconData:
    from xpra.codecs.image import to_png
    w, h = img.size
    return "png", w, h, to_png(img)


def is_icon_name(icon_string: str) -> bool:
    return bool(ICON_NAME_RE.fullmatch(icon_string))


def strip_unsafe_markup(body: str) -> str:
    # repeat until nothing is left to strip,
    # so that removing one tag cannot reveal another: `<im<img>g src=...>`
    while True:
        stripped = UNSAFE_MARKUP_RE.sub("", body)
        if stripped == body:
            return body
        body = stripped


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)] + "\u2026"


def limit_actions(actions: Sequence[str]) -> list[str]:
    # the keys are sent back to the application, so they cannot be truncated:
    # skip the actions whose key is too long
    limited: list[str] = []
    # (and an odd number of strings would make the last one a key without a label)
    for i in range(0, len(actions) - 1, 2):
        key, label = actions[i], actions[i + 1]
        # (the server refuses the keys that are not printable)
        if len(key) > MAX_ACTION_KEY or not key.isprintable():
            continue
        limited += [key, truncate(single_line(label), MAX_ACTION_LABEL)]
        if len(limited) >= MAX_ACTIONS * 2:
            break
    return limited


def valid_text(text: str) -> str:
    # lone surrogates cannot be encoded, and dbus would refuse the whole notification:
    return text.encode("utf8", "replace").decode("utf8")


def clean_text(text: str) -> str:
    return valid_text(text).translate(TEXT_STRIP)


def single_line(text: str) -> str:
    return valid_text(text).translate(SINGLE_LINE_STRIP)


def clamp_expire_timeout(expire_timeout: int) -> int:
    return min(MAX_EXPIRE_TIMEOUT, max(-1, expire_timeout))


def sanitize_icon_data(icon: IconData | None) -> IconData | None:
    """
    Re-encode icon data received from a peer into a PNG of our own making.

    This is the *only* place that parses the image bytes: every notification backend,
    and the desktop notification daemon we hand the icon to, then sees an image we
    generated ourselves rather than bytes off the network. It also makes the reported
    dimensions real instead of whatever the peer claimed.
    Returns None if the data cannot be decoded.

    The client runs this on the sandboxed decode thread (see `docs/Usage/Seccomp.md`),
    so it must not touch the filesystem.
    """
    if not icon:
        return None
    Image = PIL_Image()
    if not Image:
        return None
    coding = str(icon[0])
    data = icon[3]
    try:
        # pylint: disable=import-outside-toplevel
        from xpra.codecs.pillow.decoder import open_only
        # `open_only` sniffs the actual image type from the header:
        # the encoding claimed by the peer is not trusted
        img = open_only(data, ICON_ENCODINGS)
        w, h = img.size
        if w > ICON_MAX_SIZE or h > ICON_MAX_SIZE:
            scale = min(ICON_MAX_SIZE / w, ICON_MAX_SIZE / h)
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        return image_data(img)
    except Exception as e:
        log("sanitize_icon_data(%s, %i, %i, %i bytes)", coding, icon[1], icon[2], len(data), exc_info=True)
        log.warn("Warning: dropping unparsable %r notification icon", coding)
        log.warn(" %s", e)
        return None


def get_notification_icon(icon_string: str) -> IconData | None:
    # this method *must* be called from the UI thread
    # since we may end up calling svg_to_png which uses Cairo
    #
    # the string may be:
    # * a path which we will load using pillow
    # * a name we look up in the current theme
    if not icon_string:
        return None
    MAX_SIZE = 256
    img = None
    w = h = 0
    from PIL import Image
    if os.path.isabs(icon_string):
        if os.path.exists(icon_string) and os.path.isfile(icon_string):
            try:
                if icon_string.endswith(".svg"):
                    from xpra.codecs.icon_util import svg_to_png
                    svg_data = load_binary_file(icon_string)
                    png_data = svg_to_png(icon_string, svg_data, MAX_SIZE, MAX_SIZE)
                    return "png", MAX_SIZE, MAX_SIZE, png_data
                # should we be using pillow.decoder.open_only here? meh
                img = Image.open(icon_string)
            except Exception as e:
                log("%s(%s)", Image.open, icon_string)
                log.warn("Warning: unable to load notification icon file")
                log.warn(" '%s'", icon_string)
                log.warn(" %s", e)
            else:
                w, h = img.size
        if not img:
            # we failed to load it using the absolute path,
            # so try to locate this icon without the path or extension:
            icon_string = os.path.splitext(os.path.basename(icon_string))[0]
    if not img:
        # try to find it in the theme:
        img = get_gtk_theme_icon(icon_string)
    if not img:
        return None
    if not w or not h:
        w, h = img.size
    if w > MAX_SIZE or h > MAX_SIZE:
        try:
            LANCZOS = Image.Resampling.LANCZOS
        except AttributeError:
            LANCZOS = Image.LANCZOS
        img = img.resize((MAX_SIZE, MAX_SIZE), LANCZOS)
        w = h = MAX_SIZE
    from xpra.codecs.image import to_png
    return "png", w, h, to_png(img)


def get_gtk_theme_icon(icon_string: str):
    # try to find it in the theme:
    try:
        Gtk = gi_import("Gtk")
        theme = Gtk.IconTheme.get_default()
    except ImportError:
        return None
    if not theme:
        return None
    try:
        icon = theme.load_icon(icon_string, Gtk.IconSize.BUTTON, 0)
    except Exception as e:
        log("failed to load icon '%s' from default theme: %s", icon_string, e)
        return None
    data = icon.get_pixels()
    w = icon.get_width()
    h = icon.get_height()
    rowstride = icon.get_rowstride()
    mode = "RGB"
    if icon.get_has_alpha():
        mode = "RGBA"
    from PIL import Image
    return Image.frombytes(mode, (w, h), data, "raw", mode, rowstride)


def get_notification_service_name(timeout=1000) -> str:
    """
    the name of the notification service currently running on the session bus,
    as returned by `GetServerInformation` (name, vendor, version, spec-version),
    or an empty string if we cannot find out.
    This is used to detect notification loops: see `PROXY_NAME`.
    """
    try:
        Gio = gi_import("Gio")
        GLib = gi_import("GLib")
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # `NO_AUTO_START`: if there is no notification service, we don't want to start one
        r = bus.call_sync(BUS_NAME, BUS_PATH, BUS_NAME, "GetServerInformation", None,
                          GLib.VariantType.new("(ssss)"), Gio.DBusCallFlags.NO_AUTO_START, timeout, None)
        name = str(r.unpack()[0])
    except Exception as e:
        log("get_notification_service_name()", exc_info=True)
        log("cannot query the notification service: %s", e)
        return ""
    log("get_notification_service_name()=%r", name)
    return name


# Ensure that the hints are of the correct type:
def validated_hints(h: dict) -> dict[str, int | bool | str]:
    hints: dict[str, int | bool | str] = {}
    for attr, atype in {
        "action-icons": bool,
        "category": str,
        # not "desktop-entry": that would let the remote application claim to be a local one
        "resident": bool,
        "transient": bool,
        "x": int,
        "y": int,
        "urgency": int,
    }.items():
        if attr not in h:
            continue
        value = h.get(attr)
        try:
            validated = atype(value)
        except (ValueError, TypeError) as e:
            log.warn("Warning: unable to parse %r as a %s: %s", value, atype, e)
            continue
        else:
            if attr == "urgency":
                # low, normal or critical:
                validated = min(2, max(0, validated))
            elif atype is str:
                validated = single_line(validated)
            hints[attr] = validated
    return hints


# dbus image / icon hints lookup:
# (try all attribute names from spec 0.9 onwards)
def image_data_hint(hints: dict) -> IconData | None:
    for attr in ("image-data", "image_data", "image-path", "image_path", "icon_data"):
        value = hints.pop(attr, "")
        if not value:
            continue
        if attr.endswith("path"):
            if not os.path.isabs(value) and POSIX and not OSX:
                from xpra.platform.posix.menu_helper import do_find_icon
                name = value
                value = do_find_icon(value, extensions=ICON_EXTENSIONS)
                log("do_find_icon(%s, %s)=%s", name, ICON_EXTENSIONS, value)
            icon_data = parse_image_path(value)
        else:
            icon_data = parse_image_data(value)
        if icon_data:
            log("parse_hints(..) using image-data from %r", attr)
            return icon_data
    return None


def decompress_image_data(icon_data: IconData) -> tuple[int, int, int, bool, int, int, bytearray]:
    try:
        from xpra.codecs.pillow.decoder import open_only  # pylint: disable=import-outside-toplevel
        img_data = icon_data[3]
        img = open_only(img_data, ("png",))
        w, h = img.size
        channels = len(img.mode)
        rowstride = w * channels
        has_alpha = img.mode == "RGBA"
        pixel_data = bytearray(img.tobytes("raw", img.mode))
        return w, h, rowstride, has_alpha, 8, channels, pixel_data
    except Exception as e:
        log("decompress_image_data(%s)", icon_data, exc_info=True)
        log.error("Error parsing notification image:")
        log.estr(e)
        return 0, 0, 0, False, 0, 0, bytearray()
