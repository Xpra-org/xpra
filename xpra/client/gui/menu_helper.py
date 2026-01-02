# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable
from typing import TypeVar

from xpra.common import noop
from xpra.platform.gui import get_icon_size
from xpra.log import Logger

log = Logger("menu")


ImageMenuItem = TypeVar("ImageMenuItem")
MenuItem = TypeVar("MenuItem")


class MenuHelper:

    def __init__(self, client):
        self.menu = None
        self.menu_shown = False
        self.menu_icon_size = get_icon_size()
        self.handshake_menuitem: Callable = self.do_handshake_menuitem
        self.set_client(client)

    def set_client(self, client) -> None:
        if client:
            self.client = client

            def shortcut() -> None:
                self.handshake_menuitem = self.menuitem

            client.after_handshake(shortcut)

    def build(self):
        log(f"build() menu={self.menu}")
        if self.menu is None:
            try:
                self.menu = self.setup_menu()
            except Exception as e:
                log.error("Error: failed to setup menu", exc_info=True)
                log.estr(e)
        return self.menu

    def set_sensitive(self, menuitem, sensitive: bool):
        raise NotImplementedError

    def setup_menu(self):
        raise NotImplementedError()

    def cleanup(self) -> None:
        self.close_menu()

    def close_menu(self) -> None:
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *args) -> None:
        log(f"menu_deactivated{args}")
        self.menu_shown = False

    def activate(self, button=1, time=0) -> None:
        log("activate(%s, %s)", button, time)
        self.show_menu(button, time)

    def popup(self, button: int, time) -> None:
        log("popup(%s, %s)", button, time)
        self.show_menu(button, time)

    def show_menu(self, button: int, time) -> None:
        self.close_menu()
        if not self.menu:
            log.warn("Warning: menu is not available yet")
            return
        self.do_show_menu(button, time)
        self.menu_shown = True

    def do_show_menu(self, button: int, time):
        raise NotImplementedError

    def show_shortcuts(self, *args) -> None:
        self.client.show_shorcuts(*args)

    def show_session_info(self, *args) -> None:
        self.client.show_session_info(*args)

    def show_bug_report(self, *args) -> None:
        self.client.show_bug_report(*args)

    def show_debug_config(self, *args) -> None:
        self.client.show_debug_config(*args)

    def get_image(self, icon_name, size=None):
        raise NotImplementedError()

    def after_handshake(self, cb: Callable, *args) -> None:
        if self.client:
            self.client.after_handshake(cb, *args)

    def do_handshake_menuitem(self, *args, **kwargs) -> ImageMenuItem:
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        self.set_sensitive(mi, False)

        def enable_menuitem(*_args) -> None:
            self.set_sensitive(mi, True)

        self.after_handshake(enable_menuitem)
        return mi

    def menuitem(self, title, icon_name="", tooltip="", cb: Callable = noop, **kwargs):
        raise NotImplementedError()

    def make_aboutmenuitem(self) -> ImageMenuItem:
        from xpra.gtk.dialogs.about import about
        return self.menuitem("About Xpra", "xpra.png", cb=about)

    def make_docsmenuitem(self) -> ImageMenuItem:
        from xpra.scripts.main import show_docs
        from xpra.scripts.config import find_docs_path
        docs_menuitem = self.menuitem("Documentation", "documentation.png", cb=show_docs)
        if not find_docs_path():
            docs_menuitem.set_tooltip_text("documentation not found!")
            self.set_sensitive(docs_menuitem, False)
        return docs_menuitem

    def make_html5menuitem(self) -> ImageMenuItem:
        def show_html5() -> None:
            from xpra.scripts.main import run_html5
            from xpra.util.thread import start_thread
            url_options = {}
            try:
                for k in ("port", "host", "username", "mode", "display"):
                    v = self.client.display_desc.get(k)
                    if v is not None:
                        url_options[k] = v
            except Exception:
                pass
            start_thread(run_html5, "open HTML5 client", True, args=(url_options,))

        from xpra.scripts.config import find_html5_path
        html5_menuitem = self.menuitem("HTML5 client", "browser.png", cb=show_html5)
        if not find_html5_path():
            html5_menuitem.set_tooltip_text("html5 client not found!")
            self.set_sensitive(html5_menuitem, False)
        return html5_menuitem

    def make_closemenuitem(self) -> ImageMenuItem:
        return self.menuitem("Close Menu", "close.png", cb=self.close_menu)
