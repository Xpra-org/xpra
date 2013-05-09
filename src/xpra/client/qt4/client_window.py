# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from PyQt4.QtGui import QWidget, QPainter
from PyQt4.QtCore import Qt

from xpra.util import AdHocStruct
from xpra.client.client_window_base import ClientWindowBase
from xpra.client.qt4.pixmap_backing import QtPixmapBacking
from xpra.log import Logger
log = Logger()
debug = log.info

MODIFIERS = {Qt.AltModifier     : "mod1",
             Qt.ShiftModifier   : "shift",
             Qt.ControlModifier : "control",
             }


class QtKeyEvent(AdHocStruct):
    pass

"""
Qt4 version of the ClientWindow class
"""
class ClientWindow(QWidget, ClientWindowBase):

    NAME_TO_HINT = {
                "NORMAL"        : Qt.Widget,
                "DIALOG"        : Qt.Dialog,
                #"MENU"          : Qt??,
                "TOOLBAR"       : Qt.Tool,
                "SPLASH"        : Qt.SplashScreen,
                "UTILITY"       : Qt.Tool,
                #"DOCK"          : Qt???,
                "DESKTOP"       : Qt.Desktop,
                "DROPDOWN_MENU" : Qt.Popup,
                "POPUP_MENU"    : Qt.Popup,
                "TOOLTIP"       : Qt.ToolTip,
                #"NOTIFICATION"  : Qt??,
                "COMBO"         : Qt.SubWindow,
                #"DND"           : Qt??
                    }

    def __init__(self, *args):
        ClientWindowBase.__init__(self, *args)
        self.move(*self._pos)
        self.resize(*self._size)
        self.setMouseTracking(True)
        geom = self._pos+self._size
        self.setGeometry(*geom)
        #self.queue_draw(0, 0, *self._size)

    def init_window(self, metadata):
        QWidget.__init__(self, None)
        ClientWindowBase.init_window(self, metadata)

    def new_backing(self, w, h):
        self._backing = self.make_new_backing(QtPixmapBacking, w, h)


    def show_all(self):
        self.show()

    def hideEvent(self, event):
        debug("hideEvent(%s)", event)
        #super(QWidget, self).hideEvent(event)

    def showEvent(self, event):
        debug("showEvent(%s)", event)
        if not self._been_mapped:
            self._been_mapped = True
        #super(QWidget, self).showEvent(event)

    def set_title(self, title):
        self.setWindowTitle(title)

    def set_type_hint(self, hint):
        debug("set_type_hint(%s)", hex(hint))
        if self._override_redirect:
            hint |= Qt.FramelessWindowHint
        self.setWindowFlags(hint)

    def update_icon(self, width, height, coding, data):
        pass

    def is_mapped(self):
        return self.testAttribute(Qt.WA_Mapped)

    def is_realized(self):
        return self.testAttribute(Qt.WA_Mapped)

    def set_modal(self, modal):
        if modal:
            self.setWindowModality(Qt.WindowModal)
            #which one is right?
            #self.setWindowModality(Qt.ApplicationModal)
        else:
            self.setWindowModality(Qt.NonModal)

    def set_wmclass(self, *wmclass):
        #not supported:
        #https://git.reviewboard.kde.org/r/109560/
        pass

    def gdk_window(self):
        return  None


    def get_window_geometry(self):
        qrect = self.geometry()
        return qrect.getRect()

    def apply_geometry_hints(self, hints):
        pass
        #self.set_geometry_hints(None, **hints)

    def queue_draw(self, x, y, width, height):
        debug("queue_draw(%s, %s, %s, %s)", x, y, width, height)
        self.update(x, y, width, height)

    def render(self, target, targetOffset, sourceRegion, renderFlags):
        debug("render(%s, %s, %s, %s)", target, targetOffset, sourceRegion, renderFlags)
        QWidget.render(target, targetOffset, sourceRegion, renderFlags)

    def paintEvent(self, event):
        debug("paintEvent(%s)", event)
        rect = event.rect()
        painter = QPainter(self)
        painter.drawPixmap(rect, self._backing._backing, rect)

    def winEvent(self, message, result):
        debug("winEvent(%s, %s)", message, result)

    def moveEvent(self, event):
        debug("moveEvent(%s)", event)
        x = event.pos().x()
        y = event.pos().x()
        self._pos = x, y
        if not self._override_redirect:
            self.process_configure_event()

    def resizeEvent(self, event):
        debug("resizeEvent(%s)", event)

    def process_configure_event(self):
        x, y, w, h = self.get_window_geometry()
        w = max(1, w)
        h = max(1, h)
        assert self._client.window_configure
        debug("configure-window for wid=%s, geometry=%s, client props=%s", self._id, (x, y, w, h), self._client_properties)
        self._client.send("configure-window", self._id, x, y, w, h, self._client_properties)


    def keyPressEvent(self, event):
        key_event = self.parse_key_event(event, True)
        self._client.handle_key_action(self, key_event)

    def keyReleaseEvent(self, event):
        key_event = self.parse_key_event(event, False)
        self._client.handle_key_action(self, key_event)

    def parse_key_event(self, event, pressed):
        key_event = QtKeyEvent()
        key_event.modifiers = self.parseModifiers(event.modifiers())
        key_event.keyname = str(event.text())
        key_event.keyval = event.key()
        key_event.keycode = event.nativeScanCode()
        key_event.group = 0
        key_event.string = str(event.text())
        key_event.pressed = pressed
        #if event.key() == Qt.Key_Escape:
        #QtCore.Qt.Key_0, etc..
        debug("parse_key_event(%s, %s)=%r", event, pressed, key_event)
        return key_event

    def parseModifiers(self, modifiers):
        mod = []
        for m,name in MODIFIERS.items():
            if modifiers & m:
                mod.append(name)
        return mod


    BUTTON_MAP = {
                 Qt.LeftButton      : 1,
                 Qt.RightButton     : 2,
                 Qt.MiddleButton    : 3,
                 Qt.XButton1        : 4,
                 Qt.XButton2        : 5
                 }

    def mouseMoveEvent(self, event):
        debug("mouseMoveEvent(%s)", event)
        self.do_motion_notify_event(event)

    def mousePressEvent(self, event):
        button = self.BUTTON_MAP.get(event.button())
        debug("mousePressEvent(%s) button=%s", event, button)
        if button is not None:
            self._button_action(button, event, True)

    def mouseReleaseEvent(self, event):
        button = self.BUTTON_MAP.get(event.button())
        debug("mouseReleaseEvent(%s) button=%s", event, button)
        if button is not None:
            self._button_action(button, event, True)

    SCROLL_MAP = {
                  (Qt.Vertical, 0)      : 4,
                  (Qt.Vertical, 1)      : 5,
                  (Qt.Horizontal, 0)    : 6,
                  (Qt.Horizontal, 1)    : 7,
                  }
    #map to the same values as gtk:
    #gdk.SCROLL_UP: 4,
    #gdk.SCROLL_DOWN: 5,
    #gdk.SCROLL_LEFT: 6,
    #gdk.SCROLL_RIGHT: 7,

    def wheelEvent(self, event):
        debug("wheelEvent(%s)", event)
        if self._client.readonly:
            return
        if event.delta()>0:
            direction = 1
        else:
            direction = 0
        event_key = (event.orientation(), direction)
        scroll_event = self.SCROLL_MAP.get(event_key)
        if not scroll_event:
            return
        c = abs(event.delta())
        for _ in xrange(c):
            self._button_action(scroll_event, event, True)
            self._button_action(scroll_event, event, False)
        event.accept()

    def _pointer_modifiers(self, event):
        buttons = []
        for mask, button in self.BUTTON_MAP.items():
            if event.buttons() & mask:
                buttons.append(button)
        gpos = event.globalPos()
        modifiers = self.parseModifiers(event.modifiers())
        debug("_pointer_modifiers(%s)=(%s, %s, %s)", event, gpos, buttons, modifiers)
        return (gpos.x(), gpos.y()), buttons, modifiers
