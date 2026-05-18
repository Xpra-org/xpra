# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.os_util import POSIX
from xpra.net.common import FULL_INFO


def get_server_base_classes() -> tuple[type, ...]:
    from xpra.server import features
    from xpra.server.core import ServerCore
    classes: list[type] = [ServerCore]
    # `Ping`, `Bandwidth` and `ControlComands` don't have any dependencies:
    # (Ping has been migrated to a standalone instance — see
    # `get_instance_subsystem_classes` below.)

    if features.gtk:
        if features.x11:
            from xpra.x11.subsystem.gtk import GtkX11Server
            classes.append(GtkX11Server)
        else:
            from xpra.server.subsystem.gtk import GTKServer
            classes.append(GTKServer)
    elif features.x11:
        from xpra.x11.subsystem.x11init import X11Init
        classes.append(X11Init)
    if features.display:
        if features.x11:
            from xpra.x11.subsystem.display import X11DisplayManager
            classes.append(X11DisplayManager)
        else:
            from xpra.server.subsystem.display import DisplayManager
            classes.append(DisplayManager)
    if features.keyboard:
        if features.x11:
            from xpra.x11.subsystem.keyboard import X11KeyboardServer
            classes.append(X11KeyboardServer)
        else:
            from xpra.server.subsystem.keyboard import KeyboardServer
            classes.append(KeyboardServer)
    if features.pointer:
        if features.x11:
            from xpra.x11.subsystem.pointer import X11PointerServer
            classes.append(X11PointerServer)
        else:
            from xpra.server.subsystem.pointer import PointerServer
            classes.append(PointerServer)
    if features.window:
        from xpra.server.subsystem.window import WindowServer
        classes.append(WindowServer)
    # this should only be enabled for desktop and shadow servers:
    if features.rfb:
        from xpra.server.rfb.server import RFBServer
        classes.append(RFBServer)
    return tuple(classes)


def get_instance_subsystem_classes() -> tuple[type, ...]:
    """
    Subsystems that have been migrated to standalone instance composition.
    They are NOT inherited into the dynamic ServerBaseClass MRO; instead,
    each is constructed as an instance and stored in `self.subsystems`.
    """
    from xpra.server import features
    classes: list[type] = []
    if features.ping:
        from xpra.server.subsystem.ping import PingServer
        classes.append(PingServer)
    if features.bandwidth:
        from xpra.server.subsystem.bandwidth import BandwidthServer
        classes.append(BandwidthServer)
    if features.debug:
        from xpra.server.subsystem.debug import DebugServer
        classes.append(DebugServer)
    if features.shell:
        from xpra.server.subsystem.shell import ShellServer
        classes.append(ShellServer)
    if features.power:
        # server-side system power events
        from xpra.server.subsystem.power import PowerEventServer
        classes.append(PowerEventServer)
    if features.watcher:
        from xpra.server.subsystem.watcher import UIWatcher
        classes.append(UIWatcher)
    if features.suspend:
        # processes power event messages from the client
        from xpra.server.subsystem.suspend import SuspendServer
        classes.append(SuspendServer)
    if features.idle:
        from xpra.server.subsystem.idle import IdleTimeoutServer
        classes.append(IdleTimeoutServer)
    if POSIX and FULL_INFO >= 1:
        from xpra.server.subsystem.drm import DRMInfo
        classes.append(DRMInfo)
    if features.http:
        from xpra.server.subsystem.http import HttpServer
        classes.append(HttpServer)
    if features.ssh:
        from xpra.server.subsystem.ssh_agent import SshAgent
        classes.append(SshAgent)
    if features.dbus:
        from xpra.server.subsystem.dbus import DbusServer
        classes.append(DbusServer)
    # EncryptionServer is unconditional - it gracefully no-ops when no
    # encryption is configured on a given socket. `core.make_protocol`
    # calls `enc.parse_encryption(...)` only if the subsystem is present.
    from xpra.server.subsystem.encryption import EncryptionServer
    classes.append(EncryptionServer)
    if features.command:
        from xpra.server.subsystem.menu import MenuServer
        classes.append(MenuServer)
    if features.logging:
        from xpra.server.subsystem.logging import LoggingServer
        classes.append(LoggingServer)
    if features.tray:
        from xpra.server.subsystem.tray import TrayMenu
        classes.append(TrayMenu)
    if features.opengl:
        from xpra.server.subsystem.opengl import OpenGLInfo
        classes.append(OpenGLInfo)
    if features.mmap:
        from xpra.server.subsystem.mmap import MMAP_Server
        classes.append(MMAP_Server)
    if features.notification:
        from xpra.server.subsystem.notification import NotificationForwarder
        classes.append(NotificationForwarder)
    if features.webcam:
        from xpra.server.subsystem.webcam import WebcamServer
        classes.append(WebcamServer)
    if features.clipboard:
        from xpra.server.subsystem.clipboard import ClipboardServer
        classes.append(ClipboardServer)
    if features.pulseaudio:
        from xpra.server.subsystem.pulseaudio import PulseaudioServer
        classes.append(PulseaudioServer)
    if features.audio:
        from xpra.server.subsystem.audio import AudioServer
        classes.append(AudioServer)
    if features.encoding:
        from xpra.server.subsystem.encoding import EncodingServer
        classes.append(EncodingServer)
    # ChildCommandServer should be last so that the environment is fully prepared:
    if features.command:
        from xpra.server.subsystem.command import ChildCommandServer
        classes.append(ChildCommandServer)
    if features.file:
        from xpra.server.subsystem.file import FileServer
        classes.append(FileServer)
    if features.printer:
        from xpra.server.subsystem.printer import PrinterServer
        classes.append(PrinterServer)
    if features.x11 and features.display:
        from xpra.x11.subsystem.icc import ICCServer
        classes.append(ICCServer)
    if features.x11 and features.bell:
        from xpra.x11.subsystem.bell import BellServer
        classes.append(BellServer)
    if features.x11 and features.systray:
        from xpra.x11.subsystem.systray import SystemTrayServer
        classes.append(SystemTrayServer)
    from xpra.server.subsystem.sharing import SharingServer
    classes.append(SharingServer)
    if features.cursor:
        if features.x11:
            from xpra.x11.subsystem.cursor import XCursorServer
            classes.append(XCursorServer)
        else:
            from xpra.server.subsystem.cursor import CursorManager
            classes.append(CursorManager)
    if features.x11 and features.display:
        from xpra.x11.subsystem.xsettings import XSettingsServer
        classes.append(XSettingsServer)
    return tuple(classes)
