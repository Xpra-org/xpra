# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gtk, import_glib
gtk = import_gtk()
glib = import_glib()

from xpra.util import CLIENT_EXIT, iround, envbool
from xpra.os_util import bytestostr, OSX
from xpra.gtk_common.gtk_util import ensure_item_selected, menuitem, popup_menu_workaround, CheckMenuItem, MESSAGE_QUESTION, BUTTONS_NONE
from xpra.client.client_base import EXIT_OK
from xpra.gtk_common.about import about, close_about
from xpra.codecs.loader import PREFERED_ENCODING_ORDER, ENCODINGS_HELP, ENCODINGS_TO_NAME
from xpra.platform.gui import get_icon_size
try:
    from xpra.clipboard.translated_clipboard import TranslatedClipboardProtocolHelper
except ImportError:
    TranslatedClipboardProtocolHelper = None
try:
    from xpra import clipboard
    HAS_CLIPBOARD = bool(clipboard)
except ImportError:
    HAS_CLIPBOARD = False

from xpra.log import Logger
log = Logger("menu")
clipboardlog = Logger("menu", "clipboard")
webcamlog = Logger("menu", "webcam")


HIDE_DISABLED_MENU_ENTRIES = OSX

SHOW_UPLOAD = envbool("XPRA_SHOW_UPLOAD_MENU", True)
STARTSTOP_SOUND_MENU = envbool("XPRA_SHOW_SOUND_MENU", True)
WEBCAM_MENU = envbool("XPRA_SHOW_WEBCAM_MENU", True)
RUNCOMMAND_MENU = envbool("XPRA_SHOW_RUNCOMMAND_MENU", True)
SHOW_CLIPBOARD_MENU = envbool("XPRA_SHOW_CLIPBOARD_MENU", HAS_CLIPBOARD)
SHOW_SHUTDOWN = envbool("XPRA_SHOW_SHUTDOWN", True)
WINDOWS_MENU = envbool("XPRA_SHOW_WINDOWS_MENU", True)


LOSSLESS = "Lossless"
QUALITY_OPTIONS_COMMON = {
                50      : "Average",
                30      : "Low",
                }
MIN_QUALITY_OPTIONS = QUALITY_OPTIONS_COMMON.copy()
MIN_QUALITY_OPTIONS[0] = "None"
MIN_QUALITY_OPTIONS[75] = "High"
QUALITY_OPTIONS = QUALITY_OPTIONS_COMMON.copy()
QUALITY_OPTIONS[0]  = "Auto"
QUALITY_OPTIONS[1]  = "Lowest"
QUALITY_OPTIONS[90]  = "Best"
QUALITY_OPTIONS[100]  = LOSSLESS


SPEED_OPTIONS_COMMON = {
                70      : "Low Latency",
                30      : "Low Bandwidth",
                }
MIN_SPEED_OPTIONS = SPEED_OPTIONS_COMMON.copy()
MIN_SPEED_OPTIONS[0] = "None"
SPEED_OPTIONS = SPEED_OPTIONS_COMMON.copy()
SPEED_OPTIONS[0]    = "Auto"
SPEED_OPTIONS[1]    = "Lowest Bandwidth"
SPEED_OPTIONS[100]  = "Lowest Latency"

CLIPBOARD_LABELS = ["Clipboard", "Primary", "Secondary"]
CLIPBOARD_LABEL_TO_NAME = {
                           "Clipboard"  : "CLIPBOARD",
                           "Primary"    : "PRIMARY",
                           "Secondary"  : "SECONDARY"
                           }
CLIPBOARD_NAME_TO_LABEL  = dict((v,k) for k,v in CLIPBOARD_LABEL_TO_NAME.items())

CLIPBOARD_DIRECTION_LABELS = ["Client to server only", "Server to client only", "Both directions", "Disabled"]
CLIPBOARD_DIRECTION_LABEL_TO_NAME = {
                                     "Client to server only"    : "to-server",
                                     "Server to client only"    : "to-client",
                                     "Both directions"          : "both",
                                     "Disabled"                 : "disabled",
                                     }
CLIPBOARD_DIRECTION_NAME_TO_LABEL = dict((v,k) for k,v in CLIPBOARD_DIRECTION_LABEL_TO_NAME.items())


def ll(m):
    try:
        return "%s:%s" % (type(m), m.get_label())
    except:
        return str(m)

def set_sensitive(widget, sensitive):
    if OSX:
        if sensitive:
            widget.show()
        else:
            widget.hide()
    widget.set_sensitive(sensitive)


def make_min_auto_menu(title, min_options, options, get_current_min_value, get_current_value, set_min_value_cb, set_value_cb):
    #note: we must keep references to the parameters on the submenu
    #(closures and gtk callbacks don't mix so well!)
    submenu = gtk.Menu()
    submenu.get_current_min_value = get_current_min_value
    submenu.get_current_value = get_current_value
    submenu.set_min_value_cb = set_min_value_cb
    submenu.set_value_cb = set_value_cb
    fstitle = gtk.MenuItem("Fixed %s:" % title)
    set_sensitive(fstitle, False)
    submenu.append(fstitle)
    submenu.menu_items = {}
    submenu.min_menu_items = {}
    def populate_menu(options, value, set_fn):
        found_match = False
        items = {}
        if value and value>0 and value not in options:
            options[value] = "%s%%" % value
        for s in sorted(options.keys()):
            t = options.get(s)
            qi = CheckMenuItem(t)
            qi.set_draw_as_radio(True)
            candidate_match = s>=max(0, value)
            qi.set_active(not found_match and candidate_match)
            found_match |= candidate_match
            qi.connect('activate', set_fn, submenu)
            if s>0:
                qi.set_tooltip_text("%s%%" % s)
            submenu.append(qi)
            items[s] = qi
        return items
    def set_value(item, ss):
        if not item.get_active():
            return
        #user select a new value from the menu:
        s = -1
        for ts,tl in options.items():
            if tl==item.get_label():
                s = ts
                break
        if s>=0 and s!=ss.get_current_value():
            log("setting %s to %s", title, s)
            ss.set_value_cb(s)
            #deselect other items:
            for x in ss.menu_items.values():
                if x!=item:
                    x.set_active(False)
            #min is only relevant in auto-mode:
            if s!=0:
                for v,x in ss.min_menu_items.items():
                    x.set_active(v==0)
    submenu.menu_items.update(populate_menu(options, get_current_value(), set_value))
    submenu.append(gtk.SeparatorMenuItem())
    mstitle = gtk.MenuItem("Minimum %s:" % title)
    set_sensitive(mstitle, False)
    submenu.append(mstitle)
    def set_min_value(item, ss):
        if not item.get_active():
            return
        #user selected a new min-value from the menu:
        s = -1
        for ts,tl in min_options.items():
            if tl==item.get_label():
                s = ts
                break
        if s>=0 and s!=ss.get_current_min_value():
            log("setting min-%s to %s", title, s)
            ss.set_min_value_cb(s)
            #deselect other min items:
            for x in ss.min_menu_items.values():
                if x!=item:
                    x.set_active(False)
            #min requires auto-mode:
            for x in ss.menu_items.values():
                if x.get_label()=="Auto":
                    if not x.get_active():
                        x.activate()
                else:
                    x.set_active(False)
    mv = -1
    if get_current_value()<=0:
        mv = get_current_min_value()
    submenu.min_menu_items.update(populate_menu(min_options, mv, set_min_value))
    submenu.show_all()
    return submenu

def make_encodingsmenu(get_current_encoding, set_encoding, encodings, server_encodings):
    encodings_submenu = gtk.Menu()
    populate_encodingsmenu(encodings_submenu, get_current_encoding, set_encoding, encodings, server_encodings)
    return encodings_submenu

def populate_encodingsmenu(encodings_submenu, get_current_encoding, set_encoding, encodings, server_encodings):
    encodings_submenu.get_current_encoding = get_current_encoding
    encodings_submenu.set_encoding = set_encoding
    encodings_submenu.encodings = encodings
    encodings_submenu.server_encodings = server_encodings
    encodings_submenu.index_to_encoding = {}
    encodings_submenu.encoding_to_index = {}
    NAME_TO_ENCODING = {}
    for i, encoding in enumerate(encodings):
        name = ENCODINGS_TO_NAME.get(encoding, encoding)
        descr = ENCODINGS_HELP.get(encoding)
        NAME_TO_ENCODING[name] = encoding
        encoding_item = CheckMenuItem(name)
        if descr:
            if encoding not in server_encodings:
                descr += "\n(not available on this server)"
            encoding_item.set_tooltip_text(descr)
        def encoding_changed(item):
            ensure_item_selected(encodings_submenu, item)
            enc = NAME_TO_ENCODING.get(item.get_label())
            log("encoding_changed(%s) enc=%s, current=%s", item, enc, encodings_submenu.get_current_encoding())
            if enc is not None and encodings_submenu.get_current_encoding()!=enc:
                encodings_submenu.set_encoding(enc)
        log("make_encodingsmenu(..) encoding=%s, current=%s, active=%s", encoding, get_current_encoding(), encoding==get_current_encoding())
        encoding_item.set_active(encoding==get_current_encoding())
        sensitive = encoding in server_encodings
        if not sensitive and HIDE_DISABLED_MENU_ENTRIES:
            continue
        set_sensitive(encoding_item, encoding in server_encodings)
        encoding_item.set_draw_as_radio(True)
        encoding_item.connect("toggled", encoding_changed)
        encodings_submenu.append(encoding_item)
        encodings_submenu.index_to_encoding[i] = encoding
        encodings_submenu.encoding_to_index[encoding] = i
    encodings_submenu.show_all()


class GTKTrayMenuBase(object):

    def __init__(self, client):
        self.client = client
        self.session_info = None
        self.menu = None
        self.menu_shown = False
        self.menu_icon_size = 0

    def build(self):
        if self.menu is None:
            show_close = True #or WIN32
            self.menu = self.setup_menu(show_close)
        return self.menu

    def show_session_info(self, *args):
        self.client.show_session_info(*args)

    def show_bug_report(self, *args):
        self.client.show_bug_report(*args)


    def get_image(self, *args):
        return self.client.get_image(*args)

    def setup_menu(self, show_close=True):
        self.menu_shown = False
        self.menu_icon_size = get_icon_size()
        menu = gtk.Menu()
        menu.set_title(self.client.session_name or "Xpra")
        def set_menu_title(*args):
            #set the real name when available:
            m = self.menu
            if m:
                m.set_title(self.client.session_name or "Xpra")
        self.client.after_handshake(set_menu_title)

        menu.append(self.make_infomenuitem())
        menu.append(self.make_featuresmenuitem())
        if self.client.keyboard_helper:
            menu.append(self.make_layoutsmenuitem())
        if SHOW_CLIPBOARD_MENU:
            menu.append(self.make_clipboardmenuitem())
        if self.client.windows_enabled:
            menu.append(self.make_picturemenuitem())
        if STARTSTOP_SOUND_MENU:
            menu.append(self.make_audiomenuitem())
        if WEBCAM_MENU:
            menu.append(self.make_webcammenuitem())
        if self.client.windows_enabled and WINDOWS_MENU:
            menu.append(self.make_windowsmenuitem())
        menu.append(self.make_servermenuitem())
        menu.append(self.make_disconnectmenuitem())
        if show_close:
            menu.append(self.make_closemenuitem())
        self.popup_menu_workaround(menu)
        menu.connect("deactivate", self.menu_deactivated)
        menu.show_all()
        self.menu_icon_size = 0
        return menu

    def cleanup(self):
        log("cleanup() session_info=%s", self.session_info)
        if self.session_info:
            self.session_info.destroy()
            self.session_info = None
        self.close_menu()
        close_about()

    def close_menu(self, *args):
        if self.menu_shown:
            self.menu.popdown()
            self.menu_shown = False

    def menu_deactivated(self, *args):
        self.menu_shown = False

    def activate(self, button=1, time=0):
        log("activate(%s, %s)", button, time)
        self.show_menu(button, time)

    def popup(self, button, time):
        log("popup(%s, %s)", button, time)
        self.show_menu(button, time)

    def show_menu(self, button, time):
        raise Exception("override me!")


    def handshake_menuitem(self, *args, **kwargs):
        """ Same as menuitem() but this one will be disabled until we complete the server handshake """
        mi = self.menuitem(*args, **kwargs)
        set_sensitive(mi, False)
        def enable_menuitem(*args):
            set_sensitive(mi, True)
        self.client.after_handshake(enable_menuitem)
        return mi


    def make_menu(self):
        return gtk.Menu()

    def menuitem(self, title, icon_name=None, tooltip=None, cb=None):
        """ Utility method for easily creating an ImageMenuItem """
        image = None
        if icon_name:
            icon_size = self.menu_icon_size or get_icon_size()
            image = self.get_image(icon_name, icon_size)
        return menuitem(title, image, tooltip, cb)

    def checkitem(self, title, cb=None, active=False):
        """ Utility method for easily creating a CheckMenuItem """
        check_item = CheckMenuItem(title)
        check_item.set_active(active)
        if cb:
            check_item.connect("toggled", cb)
        check_item.show()
        return check_item


    def make_infomenuitem(self):
        info_menu_item = self.menuitem("Information", "information.png", "About Xpra, session information..")
        menu = gtk.Menu()
        info_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_aboutmenuitem())
        menu.append(self.make_sessioninfomenuitem())
        menu.append(self.make_bugreportmenuitem())
        info_menu_item.show_all()
        return info_menu_item

    def make_aboutmenuitem(self):
        return  self.menuitem("About Xpra", "xpra.png", None, about)

    def make_sessioninfomenuitem(self):
        title = "Session Info"
        if self.client.session_name and self.client.session_name!="Xpra session":
            title = "Info: %s"  % self.client.session_name
        def show_session_info_cb(*args):
            #we define a generic callback to remove the arguments
            #(which contain the menu widget and are of no interest to the 'show_session_info' function)
            self.show_session_info()
        return  self.handshake_menuitem(title, "statistics.png", None, show_session_info_cb)

    def make_bugreportmenuitem(self):
        def show_bug_report_cb(*args):
            self.show_bug_report()
        return  self.handshake_menuitem("Bug Report", "bugs.png", None, show_bug_report_cb)


    def make_featuresmenuitem(self):
        features_menu_item = self.menuitem("Features", "features.png", "OpenGL, Bell, Cursor, etc..")
        menu = gtk.Menu()
        features_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_readonlymenuitem())
        menu.append(self.make_bellmenuitem())
        menu.append(self.make_notificationsmenuitem())
        if self.client.windows_enabled:
            menu.append(self.make_cursorsmenuitem())
        if self.client.client_supports_opengl:
            menu.append(self.make_openglmenuitem())
        if self.client.windows_enabled:
            menu.append(self.make_keyboardsyncmenuitem())
        features_menu_item.show_all()
        return features_menu_item
        

    def make_readonlymenuitem(self):
        def readonly_toggled(*args):
            v = self.readonly_menuitem.get_active()
            self.client.readonly = v
            log("readonly_toggled(%s) readonly=%s", args, self.client.readonly)
        self.readonly_menuitem = self.checkitem("Read-only", readonly_toggled)
        set_sensitive(self.readonly_menuitem, False)
        def set_readonly_menuitem(*args):
            log("set_readonly_menuitem%s enabled=%s", args, self.client.readonly)
            self.bell_menuitem.set_active(self.client.readonly)
            set_sensitive(self.readonly_menuitem, not self.client.server_readonly)
            if not self.client.server_readonly:
                self.bell_menuitem.set_tooltip_text("Disable all mouse and keyboard input")
            else:
                self.bell_menuitem.set_tooltip_text("Cannot disable readonly mode: the server has locked the session to read only")
        self.client.after_handshake(set_readonly_menuitem)
        return self.readonly_menuitem

    def make_bellmenuitem(self):
        c = self.client
        def bell_toggled(*args):
            can_toggle_bell = c.server_supports_bell and c.client_supports_bell
            if not can_toggle_bell:
                return
            v = self.bell_menuitem.get_active()
            changed = self.client.bell_enabled != v
            self.client.bell_enabled = v
            if changed:
                self.client.send_bell_enabled()
            log("bell_toggled(%s) bell_enabled=%s", args, self.client.bell_enabled)
        self.bell_menuitem = self.checkitem("Bell", bell_toggled)
        set_sensitive(self.bell_menuitem, False)
        def set_bell_menuitem(*args):
            log("set_bell_menuitem%s enabled=%s", args, self.client.bell_enabled)
            self.bell_menuitem.set_active(self.client.bell_enabled)
            can_toggle_bell = c.server_supports_bell and c.client_supports_bell
            set_sensitive(self.bell_menuitem, can_toggle_bell)
            if can_toggle_bell:
                self.bell_menuitem.set_tooltip_text("Forward system bell")
            else:
                self.bell_menuitem.set_tooltip_text("Cannot forward the system bell: the feature has been disabled")
        self.client.after_handshake(set_bell_menuitem)
        return  self.bell_menuitem

    def make_cursorsmenuitem(self):
        def cursors_toggled(*args):
            v = self.cursors_menuitem.get_active()
            changed = self.client.cursors_enabled != v
            self.client.cursors_enabled = v
            if changed:
                self.client.send_cursors_enabled()
            if not self.client.cursors_enabled:
                self.client.reset_cursor()
            log("cursors_toggled(%s) cursors_enabled=%s", args, self.client.cursors_enabled)
        self.cursors_menuitem = self.checkitem("Cursors", cursors_toggled)
        set_sensitive(self.cursors_menuitem, False)
        def set_cursors_menuitem(*args):
            log("set_cursors_menuitem%s enabled=%s", args, self.client.cursors_enabled)
            self.cursors_menuitem.set_active(self.client.cursors_enabled)
            c = self.client
            can_toggle_cursors = c.server_supports_cursors and c.client_supports_cursors
            set_sensitive(self.cursors_menuitem, can_toggle_cursors)
            if can_toggle_cursors:
                self.cursors_menuitem.set_tooltip_text("Forward custom mouse cursors")
            else:
                self.cursors_menuitem.set_tooltip_text("Cannot forward mouse cursors: the feature has been disabled")
        self.client.after_handshake(set_cursors_menuitem)
        return  self.cursors_menuitem

    def make_notificationsmenuitem(self):
        def notifications_toggled(*args):
            v = self.notifications_menuitem.get_active()
            changed = self.client.notifications_enabled != v
            self.client.notifications_enabled = v
            log("notifications_toggled%s active=%s changed=%s", args, v, changed)
            if changed:
                self.client.send_notify_enabled()
        self.notifications_menuitem = self.checkitem("Notifications", notifications_toggled)
        set_sensitive(self.notifications_menuitem, False)
        def set_notifications_menuitem(*args):
            log("set_notifications_menuitem%s enabled=%s", args, self.client.notifications_enabled)
            self.notifications_menuitem.set_active(self.client.notifications_enabled)
            can_notify = self.client.client_supports_notifications
            set_sensitive(self.notifications_menuitem, can_notify)
            if can_notify:
                self.notifications_menuitem.set_tooltip_text("Forward system notifications")
            else:
                self.notifications_menuitem.set_tooltip_text("Cannot forward system notifications: the feature has been disabled")
        self.client.after_handshake(set_notifications_menuitem)
        return self.notifications_menuitem


    def remote_clipboard_changed(self, item, clipboard_submenu):
        c = self.client
        if not c or not c.server_supports_clipboard or not c.client_supports_clipboard:
            return
        #prevent infinite recursion where ensure_item_selected
        #ends up calling here again
        key = "_in_remote_clipboard_changed"
        ich = getattr(clipboard_submenu, key, False)
        clipboardlog("remote_clipboard_changed%s already in change handler: %s, visible=%s", (ll(item), clipboard_submenu), ich, clipboard_submenu.get_visible())
        if ich: # or not clipboard_submenu.get_visible():
            return
        try:
            setattr(clipboard_submenu, key, True)
            selected_item = ensure_item_selected(clipboard_submenu, item)
            selected = selected_item.get_label()
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME.get(selected)
            self.set_new_remote_clipboard(remote_clipboard)
        finally:
            setattr(clipboard_submenu, key, False)

    def set_new_remote_clipboard(self, remote_clipboard):
        clipboardlog("set_new_remote_clipboard(%s)", remote_clipboard)
        ch = self.client.clipboard_helper
        ch.remote_clipboard = remote_clipboard
        ch.remote_clipboards = [remote_clipboard]
        selections = [remote_clipboard]
        clipboardlog.info("server clipboard synchronization changed to %s selection", remote_clipboard)
        #tell the server what to look for:
        #(now that "clipboard-toggled" has re-enabled clipboard if necessary)
        self.client.send_clipboard_selections(selections)
        ch.send_all_tokens()

    def make_translatedclipboard_optionsmenuitem(self):
        clipboardlog("make_translatedclipboard_optionsmenuitem()")
        ch = self.client.clipboard_helper
        selection_menu = self.menuitem("Selection", None, "Choose which remote clipboard to connect to")
        selection_submenu = gtk.Menu()
        selection_menu.set_submenu(selection_submenu)
        self.popup_menu_workaround(selection_submenu)
        for label in CLIPBOARD_LABELS:
            remote_clipboard = CLIPBOARD_LABEL_TO_NAME[label]
            selection_item = CheckMenuItem(label)
            active = getattr(ch, "remote_clipboard", "CLIPBOARD")==remote_clipboard
            selection_item.set_active(active)
            selection_item.set_draw_as_radio(True)
            def remote_clipboard_changed(item):
                self.remote_clipboard_changed(item, selection_submenu)
            selection_item.connect("toggled", remote_clipboard_changed)
            selection_submenu.append(selection_item)
        selection_submenu.show_all()
        return selection_menu

    def clipboard_direction_changed(self, item, submenu):
        log("clipboard_direction_changed(%s, %s)", item, submenu)
        sel = ensure_item_selected(submenu, item, recurse=False)
        if not sel:
            return
        self.do_clipboard_direction_changed(sel.get_label() or "")

    def do_clipboard_direction_changed(self, label):
        #find the value matching this item label:
        d = CLIPBOARD_DIRECTION_LABEL_TO_NAME.get(label)
        if d and d!=self.client.client_clipboard_direction:
            log.info("clipboard synchronization direction changed to: %s", label.lower())
            self.client.client_clipboard_direction = d
            can_send = d in ("to-server", "both")
            can_receive = d in ("to-client", "both")
            self.client.clipboard_helper.set_direction(can_send, can_receive)
            #will send new tokens and may help reset things:
            self.client.emit("clipboard-toggled")

    def make_clipboardmenuitem(self):
        clipboardlog("make_clipboardmenuitem()")
        self.clipboard_menuitem = self.menuitem("Clipboard", "clipboard.png")
        set_sensitive(self.clipboard_menuitem, False)
        def set_clipboard_menu(*args):
            c = self.client
            if not c.server_supports_clipboard:
                self.clipboard_menuitem.set_tooltip_text("Server does not support clipboard synchronization")
                return
            if not c.client_supports_clipboard:
                self.client_menuitem.set_tooltip_text("Client does not support clipboard synchronization")
                return
            #add a submenu:
            set_sensitive(self.clipboard_menuitem, True)
            c = self.client
            ch = self.client.clipboard_helper
            clipboard_submenu = gtk.Menu()
            self.clipboard_menuitem.set_submenu(clipboard_submenu)
            self.popup_menu_workaround(clipboard_submenu)
            #figure out if this is a translated clipboard (win32 or osx)
            #and if so, add a submenu to change the selection we synchronize with:
            try:
                from xpra.clipboard.translated_clipboard import TranslatedClipboardProtocolHelper
                assert TranslatedClipboardProtocolHelper
                clipboardlog("set_clipboard_menu(%s) helper=%s, server=%s, client=%s", args, ch, c.server_supports_clipboard, c.client_supports_clipboard)
                if issubclass(type(ch), TranslatedClipboardProtocolHelper):
                    clipboard_submenu.append(self.make_translatedclipboard_optionsmenuitem())
                    clipboard_submenu.append(gtk.SeparatorMenuItem())
            except:
                clipboardlog.error("make_clipboardmenuitem()", exc_info=True)
            for label in CLIPBOARD_DIRECTION_LABELS:
                direction_item = CheckMenuItem(label)
                d = CLIPBOARD_DIRECTION_LABEL_TO_NAME.get(label)
                direction_item.set_active(d==self.client.client_clipboard_direction)
                direction_item.connect("toggled", self.clipboard_direction_changed, clipboard_submenu)
                clipboard_submenu.append(direction_item)
            clipboard_submenu.show_all()
        self.client.after_handshake(set_clipboard_menu)
        return self.clipboard_menuitem


    def make_keyboardsyncmenuitem(self):
        def set_keyboard_sync_tooltip():
            kh = self.client.keyboard_helper
            if not kh:
                self.keyboard_sync_menuitem.set_tooltip_text("Keyboard support is not loaded")
            elif kh.keyboard_sync:
                self.keyboard_sync_menuitem.set_tooltip_text("Disable keyboard synchronization (prevents spurious key repeats on high latency connections)")
            else:
                self.keyboard_sync_menuitem.set_tooltip_text("Enable keyboard state synchronization")
        def keyboard_sync_toggled(*args):
            self.client.keyboard_sync = self.keyboard_sync_menuitem.get_active()
            log("keyboard_sync_toggled(%s) keyboard_sync=%s", args, self.client.keyboard_sync)
            set_keyboard_sync_tooltip()
            self.client.emit("keyboard-sync-toggled")
        self.keyboard_sync_menuitem = self.checkitem("Keyboard Synchronization", keyboard_sync_toggled)
        set_sensitive(self.keyboard_sync_menuitem, False)
        def set_keyboard_sync_menuitem(*args):
            kh = self.client.keyboard_helper
            set_sensitive(self.keyboard_sync_menuitem, bool(kh))
            if kh:
                log("set_keyboard_sync_menuitem%s enabled=%s", args, kh.keyboard_sync)
            self.keyboard_sync_menuitem.set_active(bool(kh) and bool(kh.keyboard_sync))
            set_keyboard_sync_tooltip()
        self.client.after_handshake(set_keyboard_sync_menuitem)
        return self.keyboard_sync_menuitem

    def make_openglmenuitem(self):
        gl = self.checkitem("OpenGL")
        def gl_set(*args):
            log("gl_set(%s) opengl_enabled=%s, ", args, self.client.opengl_enabled)
            gl.set_active(self.client.opengl_enabled)
            set_sensitive(gl, self.client.client_supports_opengl)
            def opengl_toggled(*args):
                log("opengl_toggled%s", args)
                self.client.toggle_opengl()
            gl.connect("toggled", opengl_toggled)
        self.client.after_handshake(gl_set)
        return gl

    def make_picturemenuitem(self):
        picture_menu_item = self.menuitem("Picture", "picture.png", "Encoding, quality, ..")
        menu = gtk.Menu()
        picture_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        if self.client.windows_enabled and len(self.client.get_encodings())>1:
            menu.append(self.make_encodingsmenuitem())
        if self.client.can_scale:
            menu.append(self.make_scalingmenuitem())
        menu.append(self.make_qualitymenuitem())
        menu.append(self.make_speedmenuitem())
        picture_menu_item.show_all()
        return picture_menu_item

    def make_encodingsmenuitem(self):
        encodings = self.menuitem("Encoding", "encoding.png", "Choose picture data encoding", None)
        set_sensitive(encodings, False)
        def set_encodingsmenuitem(*args):
            log("set_encodingsmenuitem%s", args)
            set_sensitive(encodings, not self.client.mmap_enabled)
            if self.client.mmap_enabled:
                #mmap disables encoding and uses raw rgb24
                encodings.set_label("Encoding")
                encodings.set_tooltip_text("memory mapped transfers are in use so picture encoding is disabled")
            else:
                encodings.set_submenu(self.make_encodingssubmenu())
        self.client.after_handshake(set_encodingsmenuitem)
        return encodings

    def make_encodingssubmenu(self, handshake_complete=True):
        server_encodings = list(self.client.server_encodings)
        all_encodings = [x for x in PREFERED_ENCODING_ORDER if x in self.client.get_encodings()]
        encodings = [x for x in all_encodings if x not in self.client.server_encodings_problematic]
        if not encodings:
            #all we have, show the "bad" hidden ones then!
            encodings = all_encodings
        if self.client.server_auto_video_encoding:
            encodings.insert(0, "auto")
            server_encodings.insert(0, "auto")
        encodings_submenu = make_encodingsmenu(self.get_current_encoding, self.set_current_encoding, encodings, server_encodings)
        self.popup_menu_workaround(encodings_submenu)
        return encodings_submenu

    def get_current_encoding(self):
        return self.client.encoding
    def set_current_encoding(self, enc):
        self.client.set_encoding(enc)
        #these menus may need updating now:
        self.set_qualitymenu()
        self.set_speedmenu()

    def reset_encoding_options(self, encodings_menu):
        for x in encodings_menu.get_children():
            if isinstance(x, gtk.CheckMenuItem):
                encoding = x.get_label()
                active = encoding==self.client.encoding
                if active!=x.get_active():
                    x.set_active(active)
                set_sensitive(x, encoding in self.client.server_encodings)


    def make_scalingmenuitem(self):
        self.scaling = self.menuitem("Scaling", "scaling.png", "Desktop Scaling")
        def set_scalingmenuitem(*args):
            log("set_scalingmenuitem%s", args)
            set_sensitive(self.scaling, not self.client.mmap_enabled)
        self.client.after_handshake(set_scalingmenuitem)
        scaling_submenu = self.make_scalingmenu()
        self.scaling.set_submenu(scaling_submenu)
        return self.scaling

    def make_scalingmenu(self):
        scaling_submenu = gtk.Menu()
        scaling_submenu.updating = False
        self.popup_menu_workaround(scaling_submenu)
        def scalecmp(v):
            return abs(self.client.xscale-v)<0.1
        from xpra.client.ui_client_base import SCALING_OPTIONS
        def scalingitem(scalingvalue=1.0):
            pct = iround(100.0*scalingvalue)
            label = {100 : "None"}.get(pct, "%i%%" % pct)
            c = CheckMenuItem(label)
            c.scalingvalue = scalingvalue
            c.set_draw_as_radio(True)
            c.set_active(scalecmp(scalingvalue))
            def scaling_activated(item):
                if scaling_submenu.updating:
                    return
                ensure_item_selected(scaling_submenu, item)
                self.client.scaleset(item.scalingvalue, item.scalingvalue)
            c.connect('activate', scaling_activated)
            return c
        for x in SCALING_OPTIONS:
            scaling_submenu.append(scalingitem(x))
        def scaling_changed(*args):
            log("scaling_changed%s updating selected tray menu item", args)
            #find the nearest scaling option to show as current:
            scaling = (self.client.xscale + self.client.yscale)/2.0
            by_distance = dict((abs(scaling-x),x) for x in SCALING_OPTIONS)
            closest = by_distance.get(sorted(by_distance)[0], 1)
            scaling_submenu.updating = True
            for x in scaling_submenu.get_children():
                scalingvalue = getattr(x, "scalingvalue", -1)
                x.set_active(scalingvalue==closest)
            scaling_submenu.updating = False
        self.client.connect("scaling-changed", scaling_changed)
        return scaling_submenu


    def make_qualitymenuitem(self):
        self.quality = self.menuitem("Quality", "slider.png", "Picture quality", None)
        set_sensitive(self.quality, False)
        def may_enable_qualitymenu(*args):
            self.quality.set_submenu(self.make_qualitysubmenu())
            self.set_qualitymenu()
        self.client.after_handshake(may_enable_qualitymenu)
        return self.quality

    def make_qualitysubmenu(self):
        quality_submenu = make_min_auto_menu("Quality", MIN_QUALITY_OPTIONS, QUALITY_OPTIONS,
                                           self.get_min_quality, self.get_quality, self.set_min_quality, self.set_quality)
        self.popup_menu_workaround(quality_submenu)
        quality_submenu.show_all()
        return quality_submenu

    def get_min_quality(self):
        return self.client.min_quality
    def get_quality(self):
        return self.client.quality
    def set_min_quality(self, q):
        self.client.min_quality = q
        self.client.quality = 0
        self.client.send_min_quality()
        self.client.send_quality()
    def set_quality(self, q):
        self.client.min_quality = 0
        self.client.quality = q
        self.client.send_min_quality()
        self.client.send_quality()

    def set_qualitymenu(self, *args):
        if self.quality:
            can_use = not self.client.mmap_enabled and (self.client.encoding in self.client.server_encodings_with_quality or self.client.encoding=="auto")
            set_sensitive(self.quality, can_use)
            if self.client.mmap_enabled:
                self.quality.set_tooltip_text("Speed is always 100% with mmap")
                return
            elif not can_use:
                self.quality.set_tooltip_text("Not supported with %s encoding" % self.client.encoding)
                return
            self.quality.set_tooltip_text("Minimum picture quality")
            #now check if lossless is supported:
            if self.quality.get_submenu():
                can_lossless = self.client.encoding in self.client.server_encodings_with_lossless_mode
                for q,item in self.quality.get_submenu().menu_items.items():
                    set_sensitive(item, q<100 or can_lossless)


    def make_speedmenuitem(self):
        self.speed = self.menuitem("Speed", "speed.png", "Encoding latency vs size", None)
        set_sensitive(self.speed, False)
        def may_enable_speedmenu(*args):
            self.speed.set_submenu(self.make_speedsubmenu())
            self.set_speedmenu()
        self.client.after_handshake(may_enable_speedmenu)
        return self.speed

    def make_speedsubmenu(self):
        speed_submenu = make_min_auto_menu("Speed", MIN_SPEED_OPTIONS, SPEED_OPTIONS,
                                           self.get_min_speed, self.get_speed, self.set_min_speed, self.set_speed)
        self.popup_menu_workaround(speed_submenu)
        return speed_submenu

    def get_min_speed(self):
        return self.client.min_speed
    def get_speed(self):
        return self.client.speed
    def set_min_speed(self, s):
        self.client.min_speed = s
        self.client.speed = 0
        self.client.send_min_speed()
        self.client.send_speed()
    def set_speed(self, s):
        self.client.min_speed = 0
        self.client.speed = s
        self.client.send_min_speed()
        self.client.send_speed()


    def set_speedmenu(self, *args):
        if self.speed:
            can_use = not self.client.mmap_enabled and (self.client.encoding in self.client.server_encodings_with_speed or self.client.encoding=="auto")
            set_sensitive(self.speed, can_use)
            if self.client.mmap_enabled:
                self.speed.set_tooltip_text("Quality is always 100% with mmap")
            elif self.client.encoding!="h264":
                self.speed.set_tooltip_text("Not supported with %s encoding" % self.client.encoding)
            else:
                self.speed.set_tooltip_text("Encoding latency vs size")


    def make_audiomenuitem(self):
        audio_menu_item = self.menuitem("Audio", "audio.png", "Speaker and Microphone forwarding")
        menu = gtk.Menu()
        audio_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_speakermenuitem())
        menu.append(self.make_microphonemenuitem())
        audio_menu_item.show_all()
        return audio_menu_item


    def spk_on(self, *args):
        log("spk_on(%s)", args)
        self.client.start_receiving_sound()
    def spk_off(self, *args):
        log("spk_off(%s)", args)
        self.client.stop_receiving_sound()
    def make_speakermenuitem(self):
        speaker = self.menuitem("Speaker", "speaker.png", "Forward sound output from the server")
        set_sensitive(speaker, False)
        def is_speaker_on(*args):
            return self.client.speaker_enabled
        def speaker_state(*args):
            if not self.client.speaker_allowed:
                set_sensitive(speaker, False)
                speaker.set_tooltip_text("Speaker forwarding has been disabled")
                return
            if not self.client.server_sound_send:
                set_sensitive(speaker, False)
                speaker.set_tooltip_text("Server does not support speaker forwarding")
                return
            set_sensitive(speaker, True)
            speaker.set_submenu(self.make_soundsubmenu(is_speaker_on, self.spk_on, self.spk_off, "speaker-changed"))
        self.client.after_handshake(speaker_state)
        return speaker

    def mic_on(self, *args):
        log("mic_on(%s)", args)
        self.client.start_sending_sound()
    def mic_off(self, *args):
        log("mic_off(%s)", args)
        self.client.stop_sending_sound()
    def make_microphonemenuitem(self):
        microphone = self.menuitem("Microphone", "microphone.png", "Forward sound input to the server", None)
        set_sensitive(microphone, False)
        def is_microphone_on(*args):
            return self.client.microphone_enabled
        def microphone_state(*args):
            if not self.client.microphone_allowed:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Microphone forwarding has been disabled")
                return
            if not self.client.server_sound_receive:
                set_sensitive(microphone, False)
                microphone.set_tooltip_text("Server does not support microphone forwarding")
                return
            set_sensitive(microphone, True)
            microphone.set_submenu(self.make_soundsubmenu(is_microphone_on, self.mic_on, self.mic_off, "microphone-changed"))
        self.client.after_handshake(microphone_state)
        return microphone

    def sound_submenu_activate(self, item, menu, cb):
        log("submenu_uncheck(%s, %s, %s) ignore_events=%s, active=%s", item, menu, cb, menu.ignore_events, item.get_active())
        if menu.ignore_events:
            return
        ensure_item_selected(menu, item)
        if item.get_active():
            cb()

    def make_soundsubmenu(self, is_on_cb, on_cb, off_cb, client_signal):
        menu = gtk.Menu()
        menu.ignore_events = False
        def onoffitem(label, active, cb):
            c = CheckMenuItem(label)
            c.set_draw_as_radio(True)
            c.set_active(active)
            set_sensitive(c, True)
            c.connect('activate', self.sound_submenu_activate, menu, cb)
            return c
        is_on = is_on_cb()
        on = onoffitem("On", is_on, on_cb)
        off = onoffitem("Off", not is_on, off_cb)
        menu.append(on)
        menu.append(off)
        def update_soundsubmenu_state(*args):
            menu.ignore_events = True
            is_on = is_on_cb()
            log("update_soundsubmenu_state%s is_on=%s", args, is_on)
            if is_on:
                if not on.get_active():
                    on.set_active(True)
                    ensure_item_selected(menu, on)
            else:
                if not off.get_active():
                    off.set_active(True)
                    ensure_item_selected(menu, off)
            menu.ignore_events = False
        self.client.connect(client_signal, update_soundsubmenu_state)
        self.client.after_handshake(update_soundsubmenu_state)
        self.popup_menu_workaround(menu)
        menu.show_all()
        return menu

    def make_webcammenuitem(self):
        webcam = self.menuitem("Webcam", "webcam.png", "Forward webcam pictures to the server", None)
        if not self.client.webcam_forwarding:
            webcam.set_tooltip_text("Webcam forwarding is disabled")
            set_sensitive(webcam, False)
            return webcam
        from xpra.platform.webcam import get_all_video_devices, get_virtual_video_devices, add_video_device_change_callback
        #TODO: register remove_video_device_change_callback for cleanup
        menu = gtk.Menu()
        self.popup_menu_workaround(menu)
        #so we can toggle the menu items without causing yet more events and infinite loops:
        menu.ignore_events = False
        def deviceitem(label, cb, device_no=0):
            c = CheckMenuItem(label)
            c.set_draw_as_radio(True)
            c.set_active(get_active_device_no()==device_no)
            c.device_no = device_no
            def activate_cb(item, *args):
                webcamlog("activate_cb(%s, %s) ignore_events=%s", item, menu, menu.ignore_events)
                if not menu.ignore_events:
                    try:
                        menu.ignore_events = True
                        ensure_item_selected(menu, item)
                        cb(device_no)
                    finally:
                        menu.ignore_events = False
            c.connect("toggled", activate_cb, menu)
            return c
        def start_webcam(device_no=0):
            webcamlog("start_webcam(%s)", device_no)
            self.client.do_start_sending_webcam(device_no)
        def stop_webcam(device_no=0):
            webcamlog("stop_webcam(%s)", device_no)
            self.client.stop_sending_webcam()

        def get_active_device_no():
            if self.client.webcam_device is None:
                return -1
            return self.client.webcam_device_no

        def populate_webcam_menu():
            menu.ignore_events = True
            webcamlog("populate_webcam_menu()")
            for x in menu.get_children():
                menu.remove(x)
            all_video_devices = get_all_video_devices()
            off_label = "Off"
            if all_video_devices is None:
                #None means that this platform cannot give us the device names,
                #so we just use a single "On" menu item and hope for the best
                on = deviceitem("On", start_webcam)
                menu.append(on)
            else:
                on = None
                virt_devices = get_virtual_video_devices()
                non_virtual = dict([(k,v) for k,v in all_video_devices.items() if k not in virt_devices])
                for device_no,info in non_virtual.items():
                    label = info.get("card", info.get("device", str(device_no)))
                    item = deviceitem(label, start_webcam, device_no)
                    menu.append(item)
                if len(non_virtual)==0:
                    off_label = "No devices found"
            off = deviceitem(off_label, stop_webcam, -1)
            set_sensitive(off, off_label=="Off")
            menu.append(off)
            menu.show_all()
            menu.ignore_events = False
        populate_webcam_menu()

        def video_devices_changed(added=None, device=None):
            if added is not None and device:
                log.info("video device %s: %s", ["removed", "added"][added], device)
            else:
                log("video_devices_changed")
            #this callback runs in another thread,
            #and we want to wait for the devices to settle
            #so that the file permissions are correct when we try to access it:
            glib.timeout_add(1000, populate_webcam_menu)
        add_video_device_change_callback(video_devices_changed)

        webcam.set_submenu(menu)
        def webcam_changed(*args):
            webcamlog("webcam_changed%s webcam_device=%s", args, self.client.webcam_device)
            if not self.client.webcam_forwarding:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Webcam forwarding is disabled")
                return
            if self.client.server_virtual_video_devices<=0:
                set_sensitive(webcam, False)
                webcam.set_tooltip_text("Server does not support webcam forwarding")
                return
            set_sensitive(webcam, True)
            webcamlog("webcam_changed%s active device no=%s", args, get_active_device_no())
            menu.ignore_events = True
            for x in menu.get_children():
                x.set_active(x.device_no==get_active_device_no())
            menu.ignore_events = False
        self.client.connect("webcam-changed", webcam_changed)
        set_sensitive(webcam, False)
        self.client.after_handshake(webcam_changed)
        return webcam

    def make_layoutsmenuitem(self):
        keyboard = self.menuitem("Keyboard", "keyboard.png", "Select your keyboard layout", None)
        set_sensitive(keyboard, False)
        self.layout_submenu = gtk.Menu()
        keyboard.set_submenu(self.layout_submenu)
        self.popup_menu_workaround(self.layout_submenu)
        def kbitem(title, layout, variant, active=False):
            def set_layout(item):
                """ this callback updates the client (and server) if needed """
                ensure_item_selected(self.layout_submenu, item)
                layout = item.keyboard_layout
                variant = item.keyboard_variant
                kh = self.client.keyboard_helper
                kh.locked = layout!="Auto"
                if layout!=kh.layout_option or variant!=kh.variant_option:
                    if layout=="Auto":
                        #re-detect everything:
                        msg = "keyboard automatic mode"
                    else:
                        #use layout specified and send it:
                        kh.layout_option = layout
                        kh.variant_option = variant
                        msg = "new keyboard layout selected"
                    kh.update()
                    kh.send_layout()
                    kh.send_keymap()
                    log.info("%s: %s", msg, kh.layout_str())
            l = self.checkitem(title, set_layout, active)
            l.set_draw_as_radio(True)
            l.keyboard_layout = layout
            l.keyboard_variant = variant
            return l
        def keysort(key):
            c,l = key
            return c.lower()+l.lower()
        layout,layouts,variant,variants = self.client.keyboard_helper.get_layout_spec()
        full_layout_list = False
        if len(layouts)>1:
            log("keyboard layouts: %s", u",".join(bytestostr(x) for x in layouts))
            #log after removing dupes:
            def uniq(seq):
                seen = set()
                return [x for x in seq if not (x in seen or seen.add(x))]
            log.info("keyboard layouts: %s", u",".join(bytestostr(x) for x in uniq(layouts)))
            auto = kbitem("Auto", "Auto", "", True)
            self.layout_submenu.append(auto)
            if layout:
                self.layout_submenu.append(kbitem("%s" % layout, layout, ""))
            if variants:
                for v in variants:
                    self.layout_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
            for l in uniq(layouts):
                if l!=layout:
                    self.layout_submenu.append(kbitem("%s" % l, l, ""))
        elif layout and variants and len(variants)>1:
            #just show all the variants to choose from this layout
            default = kbitem("%s - Default" % layout, layout, "", True)
            self.layout_submenu.append(default)
            for v in variants:
                self.layout_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
        else:
            full_layout_list = True
            from xpra.keyboard.layouts import X11_LAYOUTS
            #show all options to choose from:
            sorted_keys = list(X11_LAYOUTS.keys())
            sorted_keys.sort(key=keysort)
            for key in sorted_keys:
                country,language = key
                layout,variants = X11_LAYOUTS.get(key)
                name = "%s - %s" % (country, language)
                if len(variants)>1:
                    #sub-menu for each variant:
                    variant = self.menuitem(name, tooltip=layout)
                    variant_submenu = gtk.Menu()
                    variant.set_submenu(variant_submenu)
                    self.popup_menu_workaround(variant_submenu)
                    self.layout_submenu.append(variant)
                    variant_submenu.append(kbitem("%s - Default" % layout, layout, None))
                    for v in variants:
                        variant_submenu.append(kbitem("%s - %s" % (layout, v), layout, v))
                else:
                    #no variants:
                    self.layout_submenu.append(kbitem(name, layout, None))
        keyboard_helper = self.client.keyboard_helper
        def set_layout_enabled(*args):
            if full_layout_list and (keyboard_helper.xkbmap_layout or keyboard_helper.xkbmap_print or keyboard_helper.xkbmap_query):
                #we have detected a layout
                #so no need to show the user the huge layout list
                keyboard.hide()
                return
            set_sensitive(keyboard, True)
        self.client.after_handshake(set_layout_enabled)
        return keyboard


    def make_windowsmenuitem(self):
        windows_menu_item = self.menuitem("Windows", "windows.png", "Windows Actions: refresh, raise, minimize")
        menu = gtk.Menu()
        windows_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        menu.append(self.make_raisewindowsmenuitem())
        menu.append(self.make_minimizewindowsmenuitem())
        menu.append(self.make_refreshmenuitem())
        windows_menu_item.show_all()
        return windows_menu_item

    def make_refreshmenuitem(self):
        def force_refresh(*args):
            log("force refresh")
            self.client.send_refresh_all()
        return self.handshake_menuitem("Refresh", "retry.png", None, force_refresh)

    def make_raisewindowsmenuitem(self):
        def raise_windows(*args):
            for win in self.client._window_to_id.keys():
                if not win.is_OR():
                    win.deiconify()
                    win.present()
        return self.handshake_menuitem("Raise Windows", "raise.png", None, raise_windows)

    def make_minimizewindowsmenuitem(self):
        def minimize_windows(*args):
            for win in self.client._window_to_id.keys():
                if not win.is_OR():
                    win.iconify()
        return self.handshake_menuitem("Minimize Windows", "minimize.png", None, minimize_windows)


    def make_servermenuitem(self):
        server_menu_item = self.menuitem("Server", "server.png", "Server Actions: run command, upload, shutdown")
        menu = gtk.Menu()
        server_menu_item.set_submenu(menu)
        self.popup_menu_workaround(menu)
        if RUNCOMMAND_MENU:
            menu.append(self.make_runcommandmenu())
        if SHOW_UPLOAD:
            menu.append(self.make_uploadmenuitem())
        if SHOW_SHUTDOWN:
            menu.append(self.make_shutdownmenuitem())
        server_menu_item.show_all()
        return server_menu_item


    def make_runcommandmenu(self):
        self.startnewcommand = self.menuitem("Run Command", "forward.png", "Run a new command on the server", self.client.show_start_new_command)
        def enable_start_new_command(*args):
            log("enable_start_new_command%s start_new_command=%s", args, self.client.start_new_commands)
            set_sensitive(self.startnewcommand, self.client.start_new_commands)
            if not self.client.start_new_commands:
                self.startnewcommand.set_tooltip_text("Not supported by the server")
        self.client.after_handshake(enable_start_new_command)
        return self.startnewcommand

    def make_uploadmenuitem(self):
        self.upload = self.menuitem("Upload File", "upload.png", "Send a file to the server", self.client.show_file_upload)
        def enable_upload(*args):
            log("enable_upload%s server_file_transfer=%s", args, self.client.remote_file_transfer)
            set_sensitive(self.upload, self.client.remote_file_transfer)
            if not self.client.remote_file_transfer:
                self.upload.set_tooltip_text("Not supported by the server")
        self.client.after_handshake(enable_upload)
        return self.upload


    def make_shutdownmenuitem(self):
        def ask_shutdown_confirm(*args):
            dialog = gtk.MessageDialog (None, 0, MESSAGE_QUESTION,
                                    BUTTONS_NONE,
                                    "Shutting down this session may cause data loss,\nare you sure you want to proceed?")
            dialog.add_button(gtk.STOCK_CANCEL, 0)
            SHUTDOWN = 1
            dialog.add_button("Shutdown", SHUTDOWN)
            response = dialog.run()
            dialog.destroy()
            if response == SHUTDOWN:
                self.client.send_shutdown_server()
        self.shutdown = self.menuitem("Shutdown Server", "shutdown.png", "Shutdown this server session", ask_shutdown_confirm)
        def enable_shutdown(*args):
            log("enable_shutdown%s can_shutdown_server=%s", args, self.client.can_shutdown_server)
            set_sensitive(self.shutdown, self.client.can_shutdown_server)
            if not self.client.can_shutdown_server:
                self.shutdown.set_tooltip_text("Disabled by the server")
        self.client.after_handshake(enable_shutdown)
        return self.shutdown

    def make_disconnectmenuitem(self):
        def menu_quit(*args):
            self.client.disconnect_and_quit(EXIT_OK, CLIENT_EXIT)
        return self.handshake_menuitem("Disconnect", "quit.png", None, menu_quit)

    def make_closemenuitem(self):
        return self.menuitem("Close Menu", "close.png", None, self.close_menu)


    def popup_menu_workaround(self, menu):
        popup_menu_workaround(menu, self.close_menu)
