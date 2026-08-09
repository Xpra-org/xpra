# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any, Final
from collections.abc import Callable, Iterable, Sequence
from urllib.parse import urlparse
from urllib.request import url2pathname

from AppKit import (
    NSStringPboardType, NSTIFFPboardType, NSPasteboard,
    NSPasteboardTypeString, NSPasteboardTypeHTML, NSPasteboardTypeRTF,
    NSPasteboardTypePDF, NSPasteboardTypePNG, NSPasteboardTypeTIFF,
    NSPasteboardTypeTabularText, NSPasteboardTypeURL, NSPasteboardTypeFileURL,
)
from CoreFoundation import NSData, CFDataGetBytes, CFDataGetLength

from xpra.clipboard.timeout import ClipboardTimeoutHelper
from xpra.clipboard.common import ClipboardCallback, ClipboardData
from xpra.clipboard.core import PREFERRED_TARGETS
from xpra.clipboard.targets import (
    _filter_targets,
    HTML_TARGETS, IMAGE_TARGETS, PDF_TARGETS, PLAIN_TEXT_TARGETS, RTF_TARGETS, URI_TARGETS,
    UTF8_TEXT_FALLBACK_TARGETS,
)
from xpra.clipboard.primary import PrimaryProxyMixin, PrimaryHelperMixin
from xpra.clipboard.proxy import ClipboardProxyCore, filter_data
from xpra.codecs.image_type import get_image_type
from xpra.util.ui_thread_watcher import get_ui_watcher
from xpra.util.str_fn import csv, Ellipsizer, bytestostr, memoryview_to_bytes
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("clipboard", "osx")

GLib = gi_import("GLib")

# `AppKit` has no constant for this one:
NSPasteboardTypeJPEG: Final[str] = "public.jpeg"

TSV_TARGETS: Sequence[str] = tuple(
    target for target in UTF8_TEXT_FALLBACK_TARGETS if target == "text/tab-separated-values"
)

# the pasteboard types we can exchange with the peer,
# mapped to the clipboard targets which can carry them.
# the order matters: it is the order in which the formats are chosen,
# and the first target of each type is the one we use to send its data:
PASTEBOARD_TARGETS: dict[str, Sequence[str]] = {
    # Structured text is accepted as a plain text fallback when received,
    # but must not be advertised for arbitrary strings copied locally.
    NSPasteboardTypeString: tuple(
        target for target in PLAIN_TEXT_TARGETS if target not in UTF8_TEXT_FALLBACK_TARGETS
    ),
    NSPasteboardTypeHTML: HTML_TARGETS,
    NSPasteboardTypeRTF: RTF_TARGETS,
    NSPasteboardTypeTabularText: TSV_TARGETS,
    NSPasteboardTypeURL: URI_TARGETS,
    NSPasteboardTypeFileURL: URI_TARGETS,
    NSPasteboardTypePNG: ("image/png", ),
    NSPasteboardTypeJPEG: ("image/jpeg", ),
    NSPasteboardTypeTIFF: ("image/tiff", ),
    NSPasteboardTypePDF: PDF_TARGETS,
}

# some applications still use the pre-UTI pasteboard type names,
# and those are discarded by the default `DISCARD_TARGETS` (ie: `^NeXT`):
LEGACY_TYPES: dict[str, str] = {
    NSStringPboardType: NSPasteboardTypeString,
    NSTIFFPboardType: NSPasteboardTypeTIFF,
    "NSHTMLPboardType": NSPasteboardTypeHTML,
    "NSRTFPboardType": NSPasteboardTypeRTF,
    "NSPDFPboardType": NSPasteboardTypePDF,
    "NSURLPboardType": NSPasteboardTypeURL,
    "Apple PDF pasteboard type": NSPasteboardTypePDF,
    "NeXT Rich Text Format v1.0 pasteboard type": NSPasteboardTypeRTF,
    "public.text": NSPasteboardTypeString,
    "public.plain-text": NSPasteboardTypeString,
}

# the pasteboard type carrying each image target:
IMAGE_TARGETS_TYPES: dict[str, str] = {
    "image/png": NSPasteboardTypePNG,
    "image/jpeg": NSPasteboardTypeJPEG,
    "image/tiff": NSPasteboardTypeTIFF,
}
IMAGE_TYPES_TARGETS: dict[str, str] = {nstype: target for target, nstype in IMAGE_TARGETS_TYPES.items()}

# the image formats we expose to the applications pasting from the pasteboard:
# `PNG` preserves the alpha channel, `TIFF` is what most native applications expect
SET_IMAGE_FORMATS: Sequence[tuple[str, str]] = (
    ("png", NSPasteboardTypePNG),
    ("tiff", NSPasteboardTypeTIFF),
)


def normalize_type(nstype: str) -> str:
    return LEGACY_TYPES.get(nstype, nstype)


def pasteboard_targets(types: Iterable[str]) -> Sequence[str]:
    """ the clipboard targets matching these pasteboard types """
    available = set(normalize_type(bytestostr(nstype)) for nstype in types)
    targets: list[str] = []
    for nstype, nstargets in PASTEBOARD_TARGETS.items():
        if nstype not in available:
            continue
        if nstype in IMAGE_TYPES_TARGETS:
            # we can convert to any of the image formats we support
            # (macOS often only exposes `TIFF` whilst most applications want `PNG`):
            nstargets = IMAGE_TARGETS
        targets += [target for target in nstargets if target not in targets]
    return _filter_targets(targets)


def get_target_groups() -> dict[str, str]:
    # the pasteboard format each target belongs to,
    # in the order in which the formats are chosen:
    # (all the image targets end up on the pasteboard as a single image)
    groups: dict[str, str] = {}
    for nstype, nstargets in PASTEBOARD_TARGETS.items():
        group = "image" if nstype in IMAGE_TYPES_TARGETS else nstype
        for target in tuple(nstargets) + (IMAGE_TARGETS if group == "image" else ()):
            groups.setdefault(target, group)
    # CSV and Markdown have no richer pasteboard representation, so receiving
    # either one falls back to the native string type. TSV is mapped above.
    for target in UTF8_TEXT_FALLBACK_TARGETS:
        groups.setdefault(target, NSPasteboardTypeString)
    return groups


TARGET_GROUPS: dict[str, str] = get_target_groups()


def select_targets(targets: Iterable[str], have: Iterable[str] = ()) -> Sequence[str]:
    """
    The targets we want to request from the peer:
    at most one per pasteboard format, skipping the formats we already have.
    """
    available = tuple(bytestostr(target) for target in targets)
    groups = set(TARGET_GROUPS.get(bytestostr(target), "") for target in have)
    selected: list[str] = []
    for target, group in TARGET_GROUPS.items():
        if group in groups or target not in available:
            continue
        groups.add(group)
        selected.append(target)
    return tuple(selected)


def decode_text(data) -> str:
    if isinstance(data, str):
        return data
    data = memoryview_to_bytes(data)
    try:
        return data.decode("utf8")
    except UnicodeDecodeError:
        return bytestostr(data)


def parse_uri_list(data) -> Sequence[str]:
    # RFC 2483 `text/uri-list`: one URI per line, `#` comments are ignored
    text = decode_text(data).replace("\r\n", "\n")
    return tuple(line for line in (x.strip() for x in text.split("\n")) if line and not line.startswith("#"))


def local_file_path(uri: str) -> str:
    """ the local path for a `file:` URI, if it exists on this system """
    parsed = urlparse(uri)
    if parsed.scheme != "file" or (parsed.netloc not in ("", "localhost")):
        return ""
    path = url2pathname(parsed.path)
    return path if os.path.exists(path) else ""


def uri_types(uris: Sequence[str]) -> dict[str, str]:
    """
    The pasteboard can only hold a single URL,
    and a `file:` URI from the peer usually points at a path which does not exist here:
    those are only exposed as plain text.
    """
    for uri in uris:
        if not uri.lower().startswith("file:"):
            return {NSPasteboardTypeURL: uri}
        if path := local_file_path(uri):
            log("local file for %r: %r", uri, path)
            return {NSPasteboardTypeFileURL: uri}
    return {}


class OSXClipboardProxy(ClipboardProxyCore):

    def __init__(self, selection, pasteboard, send_clipboard_request_handler, send_clipboard_token_handler):
        self.pasteboard = pasteboard
        self.send_clipboard_request_handler = send_clipboard_request_handler
        self.send_clipboard_token_handler = send_clipboard_token_handler
        # the targets and data received from the peer for the current selection:
        self.targets: Sequence[str] = ()
        self.target_data: ClipboardData = {}
        super().__init__(selection)
        self.update_change_count()
        # setup clipboard counter watcher:
        w = get_ui_watcher()
        w.add_alive_callback(self.timer_clipboard_check)

    def cleanup(self) -> None:
        super().cleanup()
        w = get_ui_watcher()
        if w:
            try:
                w.remove_alive_callback(self.timer_clipboard_check)
            except (KeyError, ValueError):
                pass

    def timer_clipboard_check(self) -> None:
        c = self.change_count
        self.update_change_count()
        log("timer_clipboard_check() was %s, now %s (have token: %s)", c, self.change_count, self._have_token)
        if c != self.change_count:
            self.local_clipboard_changed()

    def update_change_count(self) -> None:
        if p := self.pasteboard:
            self.change_count = p.changeCount()

    def clear(self) -> None:
        self.pasteboard.clearContents()

    def do_emit_token(self) -> None:
        if not (self._want_targets or self._greedy_client):
            self.send_clipboard_token_handler(self, {"targets": (), "data": {}})
            return
        targets = self.get_targets()
        log("do_emit_token() targets=%s", targets)

        def send_token(target_data: ClipboardData) -> None:
            self.send_clipboard_token_handler(self, {
                "targets": tuple(targets),
                "data": target_data,
            })

        if not targets or not self._greedy_client:
            send_token({})
            return
        # greedy clients want the data with the token:
        # send as many formats as the peer is interested in,
        # so that the application pasting can choose the one it prefers
        eager_targets = self.get_eager_targets(targets)
        log("do_emit_token() eager targets=%s", eager_targets)
        self.collect_contents(eager_targets, send_token)

    def get_pasteboard_string(self, nstype: str) -> str:
        value = self.pasteboard.stringForType_(nstype)
        log("stringForType_(%r)=%s", nstype, Ellipsizer(value))
        return str(value) if value else ""

    def get_pasteboard_data(self, nstype: str) -> bytes:
        nsdata = self.pasteboard.dataForType_(nstype)
        if not nsdata:
            log("no %r pasteboard data", nstype)
            return b""
        data = CFDataGetBytes(nsdata, (0, CFDataGetLength(nsdata)), None)
        log("dataForType_(%r)=%i bytes", nstype, len(data or b""))
        return data or b""

    def get_clipboard_text(self) -> str:
        for nstype in (NSPasteboardTypeString, NSStringPboardType):
            if text := self.get_pasteboard_string(nstype):
                return text
        return ""

    def get_targets(self) -> Sequence[str]:
        types = self.pasteboard.types() or ()
        targets = pasteboard_targets(types)
        log("get_targets() targets(%s)=%s", csv(types), targets)
        return targets

    def get_contents(self, target: str, got_contents: ClipboardCallback) -> None:
        log("get_contents%s", (target, got_contents))
        if target == "TARGETS":
            got_contents("ATOM", 32, self.get_targets())
            return
        try:
            data = self.get_target_data(target)
        except Exception:
            log.error("Error: failed to get %r data from the pasteboard", target, exc_info=True)
            data = b""
        got_contents(target, 8, data or b"")

    def get_target_data(self, target: str) -> bytes | str:
        if target in TSV_TARGETS:
            return self.get_pasteboard_string(NSPasteboardTypeTabularText).encode("utf8")
        if target in PLAIN_TEXT_TARGETS:
            return self.get_clipboard_text()
        if target in IMAGE_TARGETS:
            return self.get_image_contents(target) or b""
        if target in HTML_TARGETS:
            # `public.html` is usually stored as utf8 bytes,
            # but the pasteboard will convert from any other encoding for us:
            if html := self.get_pasteboard_string(NSPasteboardTypeHTML):
                return html.encode("utf8")
            return self.get_pasteboard_data(NSPasteboardTypeHTML)
        if target in RTF_TARGETS:
            return self.get_pasteboard_data(NSPasteboardTypeRTF)
        if target in PDF_TARGETS:
            return self.get_pasteboard_data(NSPasteboardTypePDF)
        if target in URI_TARGETS:
            return self.get_uri_list()
        # we don't know how to handle this target:
        log("no pasteboard type for target %r", target)
        return b""

    def get_uri_list(self) -> bytes:
        uris = []
        for item in self.pasteboard.pasteboardItems() or ():
            for nstype in (NSPasteboardTypeFileURL, NSPasteboardTypeURL):
                if uri := item.stringForType_(nstype):
                    uris.append(str(uri))
                    break
        log("get_uri_list()=%s", uris)
        # RFC 2483 `text/uri-list`: CRLF separated URIs
        return "\r\n".join(uris).encode("utf8")

    def get_image_contents(self, target: str) -> bytes:
        types = set(normalize_type(bytestostr(nstype)) for nstype in self.pasteboard.types() or ())
        # use the target requested if we have it, otherwise convert from whatever we do have:
        nstype = IMAGE_TARGETS_TYPES.get(target, "")
        if nstype not in types:
            nstype = ""
            for image_type in IMAGE_TARGETS:
                candidate = IMAGE_TARGETS_TYPES.get(image_type, "")
                if candidate in types:
                    nstype = candidate
                    break
        if not nstype:
            log("image target %r not found in %s", target, csv(types))
            return b""
        img_data = self.get_pasteboard_data(nstype)
        if not img_data:
            return b""
        src_dtype = IMAGE_TYPES_TARGETS[nstype]
        img_data = filter_data(dtype=src_dtype, dformat=8, data=img_data, trusted=False, output_dtype=target)
        log("get_image_contents(%s)=%i bytes from %r", target, len(img_data or b""), nstype)
        return img_data

    def got_token(self, targets, target_data=None, claim=True, _synchronous_client=False) -> None:
        # the remote end now owns the clipboard
        self.cancel_emit_token()
        if not self._enabled:
            return
        self._got_token_events += 1
        log("got token, selection=%s, targets=%s, target data=%s, claim=%s, can-receive=%s",
            self._selection, targets, Ellipsizer(target_data), claim, self._can_receive)
        if self._can_receive:
            self.targets = _filter_targets(targets or ())
            self.target_data = dict(target_data or {})
            if self.target_data:
                # the peer sent the data with the token: expose all of it at once
                self.set_clipboard_data(self.target_data)
                # the token can only carry the formats the peer chose to send
                # (just one of them with the legacy packet format),
                # so request the ones we are still missing:
                self.request_targets(self.targets, self.target_data)
            elif self.targets:
                self.request_targets(self.targets)
            else:
                # since we claim to be greedy,
                # the peer should have sent us the targets, if not then request them:
                self.send_clipboard_request_handler(self, self._selection, "TARGETS")
        if not claim:
            log("token packet without claim, not setting the token flag")
            return
        self._have_token = True

    def request_targets(self, targets: Iterable[str], have: Iterable[str] = ()) -> None:
        wanted = select_targets(targets, have)
        log("request_targets(%s, %s) requesting %s", csv(targets), csv(have), csv(wanted))
        for target in wanted:
            self.send_clipboard_request_handler(self, self._selection, target)

    def got_contents(self, target: str, dtype="", dformat: int = 8, data=b"") -> None:
        # if this is the special target 'TARGETS', cache the result:
        if target == "TARGETS" and dtype == "ATOM" and dformat == 32:
            self.targets = _filter_targets(data)
            log("got_contents: the peer has %s", csv(self.targets))
            self.request_targets(self.targets, self.target_data)
            return
        if dformat != 8 or not data:
            log("got_contents: no %r data", target)
            return
        # merge with the data already received for this selection,
        # so that all the formats requested end up on the pasteboard together:
        self.target_data[target] = (bytestostr(dtype) or target, dformat, data)
        self.set_clipboard_data(self.target_data)

    def set_clipboard_data(self, target_data: ClipboardData) -> None:
        items = self.convert_clipboard_data(target_data)
        if not items:
            log("set_clipboard_data(%s): nothing we can paste", Ellipsizer(target_data))
            return
        pasteboard = self.pasteboard
        pasteboard.clearContents()
        for nstype, value in items.items():
            if isinstance(value, str):
                r = pasteboard.setString_forType_(value, nstype)
            else:
                r = pasteboard.setData_forType_(NSData.dataWithData_(value), nstype)
            log("set %r pasteboard data (%i bytes)=%s", nstype, len(value), r)
        log("clipboard data available as: %s", csv(items.keys()))
        # this pasteboard change is ours: don't send it back to the peer
        self.update_change_count()

    def convert_clipboard_data(self, target_data: ClipboardData) -> dict[str, Any]:
        """
        Convert the target data received from the peer
        into the pasteboard types the applications can choose from.
        """
        items: dict[str, Any] = {}

        def add(nstype: str, value) -> None:
            # the formats are converted in preference order, so the first one wins:
            if value and nstype not in items:
                items[nstype] = value

        def find(targets: Iterable[str]):
            for target in targets:
                td = target_data.get(target)
                if td and len(td) >= 3 and td[1] == 8 and td[2]:
                    return td
            return None

        # plain text first: it must take precedence
        # over the text we may derive from the other formats
        if td := find(PLAIN_TEXT_TARGETS):
            add(NSPasteboardTypeString, decode_text(td[2]))
        if td := find(HTML_TARGETS):
            add(NSPasteboardTypeHTML, decode_text(td[2]))
        if td := find(RTF_TARGETS):
            add(NSPasteboardTypeRTF, memoryview_to_bytes(td[2]))
        if td := find(TSV_TARGETS):
            add(NSPasteboardTypeTabularText, decode_text(td[2]))
        if td := find(URI_TARGETS):
            uris = parse_uri_list(td[2])
            for nstype, uri in uri_types(uris).items():
                add(nstype, uri)
            # so that the URIs can at least be pasted as text:
            add(NSPasteboardTypeString, "\n".join(uris))
        if td := find(IMAGE_TARGETS):
            # (never let an invalid image prevent us from pasting the other formats)
            try:
                images = self.convert_image(td[0], td[2])
            except Exception as e:
                log("convert_image%s", (td[0], Ellipsizer(td[2])), exc_info=True)
                log.warn("Warning: dropping invalid %r clipboard image data", td[0])
                log.warn(" %s", e)
                images = {}
            for nstype, value in images.items():
                add(nstype, value)
        if td := find(PDF_TARGETS):
            pdf = memoryview_to_bytes(td[2])
            if pdf.startswith(b"%PDF"):
                add(NSPasteboardTypePDF, pdf)
            else:
                log.warn("Warning: dropping invalid pdf clipboard data")
        log("convert_clipboard_data(%s)=%s", csv(target_data.keys()), csv(items.keys()))
        return items

    @staticmethod
    def convert_image(dtype: str, data) -> dict[str, bytes]:
        # re-encode the image data: this also validates it
        img_type = get_image_type(data)
        if not img_type:
            log.warn("Warning: unrecognized %r clipboard image data", dtype)
            return {}
        from xpra.codecs.pillow.decoder import open_only
        from xpra.codecs.image import to_bytesbuffer
        img = open_only(data, (img_type, ))
        values: dict[str, bytes] = {}
        for save_type, nstype in SET_IMAGE_FORMATS:
            try:
                values[nstype] = to_bytesbuffer(img, save_type)
            except Exception as e:
                log("convert_image(%s, ..) failed to save as %r", dtype, save_type, exc_info=True)
                log.warn("Warning: failed to convert the clipboard image to %s", save_type)
                log.warn(" %s", e)
        return values

    def set_clipboard_text(self, text) -> None:
        self.pasteboard.clearContents()
        r = self.pasteboard.setString_forType_(text, NSPasteboardTypeString)
        log("set_clipboard_text(%s) success=%s", Ellipsizer(text), r)
        self.update_change_count()

    def local_clipboard_changed(self) -> None:
        log("local_clipboard_changed()")
        self.do_owner_changed()


class OSXPrimaryProxy(PrimaryProxyMixin, OSXClipboardProxy):
    """
    The `PRIMARY` selection does not exist on MacOS,
    see `PrimaryProxyMixin`
    """

    def __init__(self, selection, pasteboard, send_clipboard_request_handler, send_clipboard_token_handler,
                 set_clipboard_text: Callable[[str], None]):
        self.init_primary(set_clipboard_text)
        super().__init__(selection, pasteboard, send_clipboard_request_handler, send_clipboard_token_handler)

    def __repr__(self):
        return "OSXPrimaryProxy"

    def local_clipboard_changed(self) -> None:
        # a local clipboard change takes precedence
        # over any remote `PRIMARY` contents we were about to fetch:
        log("local_clipboard_changed()")
        self.cancel_request()


class OSXClipboardProtocolHelper(PrimaryHelperMixin, ClipboardTimeoutHelper):

    def __init__(self, *args, **kwargs):
        self.pasteboard = self.get_pasteboard()
        if self.pasteboard is None:
            raise RuntimeError("cannot load Pasteboard, maybe not running from a GUI session?")
        kwargs["clipboard.local"] = "CLIPBOARD"
        super().__init__(*args, **kwargs)
        # the OS requests the data as soon as we claim the clipboard,
        # so we must ask the peer to send it with the token.
        # `PRIMARY` is excluded: it is only ever saved to the `CLIPBOARD` selection,
        # and it changes far too often to request its contents every time:
        selections = tuple(x for x in self.local_selections if x != "PRIMARY")
        self.local_greedy = selections
        self.local_want_targets = selections
        if "XPRA_CLIPBOARD_PREFERRED_TARGETS" not in os.environ:
            # tell the peer about all the formats the pasteboard can expose,
            # so that it sends them to us with the token:
            extra = tuple(IMAGE_TARGETS) + tuple(PDF_TARGETS)
            self.local_preferred_targets = tuple(dict.fromkeys(PREFERRED_TARGETS + extra))

    def __repr__(self):
        return "OSXClipboardProtocolHelper"

    @staticmethod
    def get_pasteboard():
        return NSPasteboard.generalPasteboard()

    def cleanup(self) -> None:
        super().cleanup()
        self.pasteboard = None

    def make_proxy(self, selection) -> OSXClipboardProxy:
        if selection == "PRIMARY":
            proxy = OSXPrimaryProxy(selection, self.pasteboard,
                                    self._send_clipboard_request_handler, self._send_clipboard_token_handler,
                                    self.set_local_clipboard_text)
            self.primary_proxy = proxy
        else:
            proxy = OSXClipboardProxy(selection, self.pasteboard,
                                      self._send_clipboard_request_handler, self._send_clipboard_token_handler)
        proxy.set_direction(self.can_send, self.can_receive)
        return proxy

    def set_local_clipboard_text(self, text: str) -> None:
        # this is used to save the remote `PRIMARY` selection to the local `CLIPBOARD`:
        # we go through the `CLIPBOARD` proxy so that it does not claim the selection
        # when it sees the change we are making here
        proxy = self._clipboard_proxies.get("CLIPBOARD")
        if not proxy:
            log.warn("Warning: no 'CLIPBOARD' proxy to save the 'PRIMARY' selection to")
            return
        proxy.set_clipboard_text(text)
        # this pasteboard change is ours:
        # no proxy should report it as a local clipboard change
        for other in self._clipboard_proxies.values():
            other.update_change_count()

    ############################################################################
    # just pass ATOM targets through
    # (we use them internally as strings)
    ############################################################################
    def _munge_wire_selection_to_raw(self, encoding, dtype, dformat, data) -> bytes | str:
        if encoding == "atoms":
            data = _filter_targets(data)
        return super()._munge_wire_selection_to_raw(encoding, dtype, dformat, data)


def main() -> None:
    import time
    from xpra.platform import program_context
    with program_context("OSX Clipboard Change Test"):
        log.enable_debug()

        # init UI watcher with gobject (required by pasteboard monitoring code)
        get_ui_watcher()

        log.info("testing pasteboard")

        gtk = gi_import("Gtk")
        pasteboard = NSPasteboard.generalPasteboard()

        def nosend(*args):
            log("nosend%s", args)

        proxy = OSXClipboardProxy("CLIPBOARD", pasteboard, nosend, nosend)
        log.info("current change count=%s", proxy.change_count)
        clipboard = gtk.Clipboard(selection="CLIPBOARD")
        log.info("changing clipboard %s contents", clipboard)
        clipboard.set_text("HELLO WORLD %s" % time.time())
        proxy.update_change_count()
        log.info("new change count=%s", proxy.change_count)
        log.info("any update to your clipboard should get logged (^C to exit)")
        cc = proxy.change_count
        while True:
            v = proxy.change_count
            if v != cc:
                log.info("success! the clipboard change has been detected, new change count=%s", v)
            else:
                log.info(".")
            time.sleep(1)


if __name__ == "__main__":
    main()
