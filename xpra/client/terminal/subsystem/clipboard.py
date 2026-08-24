# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.util.parsing import parse_simple_dict, FALSE_OPTIONS
from xpra.client.subsystem.clipboard import ClipboardClient
from xpra.client.terminal.clipboard import OSC52Clipboard
from xpra.log import Logger

log = Logger("clipboard", "terminal")


class TerminalClipboardClient(ClipboardClient):
    """
    Clipboard subsystem for the terminal client.

    The stock helper lookup only knows about the platform backends
    (`X11Clipboard` or the GTK one on POSIX), which a terminal client must not load:
    the only clipboard we can reach is the terminal's own, using OSC 52.
    """
    __slots__ = ()

    def make_clipboard_helper(self):
        # `--clipboard=TYPE:option=value,...`: there is only one type here,
        # but the options are the same as for any other clipboard helper:
        parts = (self.client_clipboard_type or "").split(":", 1)
        if parts[0].lower() in FALSE_OPTIONS:
            log("make_clipboard_helper() clipboard is disabled: %r", self.client_clipboard_type)
            self.client_supports_clipboard = False
            return None
        options: dict[str, Any] = parse_simple_dict(parts[1]) if len(parts) > 1 else {}
        # the client owns the terminal: it is the only writer
        # (`write_osc52` is expected to defer to the UI thread if needed)
        options["osc52-write"] = self.client.write_osc52
        try:
            return self.setup_clipboard_helper(OSC52Clipboard, options)
        except (ImportError, AttributeError, RuntimeError) as e:
            log("make_clipboard_helper()", exc_info=True)
            log.error("Error: cannot instantiate the OSC 52 clipboard helper")
            log.estr(e)
        self.client_supports_clipboard = False
        return None
