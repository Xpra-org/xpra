# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.net.common import FULL_INFO
from xpra.os_util import POSIX


def get_server_subsystems(server) -> tuple[type, ...]:
    """Select the ordered ServerBase subsystems using the server's backend selectors."""
    from xpra.server import features
    classes: list[type] = []
    if features.gtk:
        if gtk_class := server.get_gtk_subsystem_class():
            classes.append(gtk_class)
    elif features.x11:
        from xpra.x11.subsystem.x11init import X11Init
        classes.append(X11Init)
    if features.dbus:
        # the dbus subsystem must come first:
        # it starts the dbus instance for this session and updates the environment,
        # any subsystem connecting to the session bus before that point
        # would be connected to the bus we inherited from the environment
        # (ie: the user's desktop session bus) - see `init_session_bus`
        from xpra.server.subsystem.dbus import DbusManager
        classes.append(DbusManager)
    # SharingServer must come before any subsystem whose `parse_hello` looks at the other clients
    # (ie: display sizing, keyboard): it may reject the new connection,
    # or disconnect older ones (ie: from the same uuid) which must not be taken into account:
    from xpra.server.subsystem.sharing import SharingServer
    classes.append(SharingServer)
    if features.ping:
        from xpra.server.subsystem.ping import PingServer
        classes.append(PingServer)
    if features.gsettings:
        from xpra.server.subsystem.gsettings import GSettingsServer
        classes.append(GSettingsServer)
    if features.register:
        from xpra.server.subsystem.register import RegisterSubsystem
        classes.append(RegisterSubsystem)
    if features.bandwidth:
        from xpra.server.subsystem.bandwidth import BandwidthManager
        classes.append(BandwidthManager)
    if features.debug:
        from xpra.server.subsystem.debug import DebugServer
        classes.append(DebugServer)
    if features.shell:
        from xpra.server.subsystem.shell import ShellServer
        classes.append(ShellServer)
    if features.power:
        from xpra.server.subsystem.power import PowerEventServer
        classes.append(PowerEventServer)
    if features.watcher:
        from xpra.server.subsystem.watcher import UIWatcher
        classes.append(UIWatcher)
    if features.suspend:
        from xpra.server.subsystem.suspend import SuspendServer
        classes.append(SuspendServer)
    if features.idle:
        from xpra.server.subsystem.idle import IdleTimeoutManager
        classes.append(IdleTimeoutManager)
    if POSIX and FULL_INFO >= 1:
        from xpra.server.subsystem.drm import DRMInfo
        classes.append(DRMInfo)
    if features.http:
        from xpra.server.subsystem.http import HttpServer
        classes.append(HttpServer)
    if features.ssh:
        from xpra.server.subsystem.ssh_agent import SshAgent
        classes.append(SshAgent)
    # EncryptionServer is unconditional - it gracefully no-ops when no
    # encryption is configured on a given socket.
    from xpra.server.subsystem.encryption import EncryptionServer
    classes.append(EncryptionServer)
    if features.menu:
        from xpra.server.subsystem.menu import MenuServer
        classes.append(MenuServer)
    if features.logging:
        from xpra.server.subsystem.logging import LoggingManager
        classes.append(LoggingManager)
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
        classes.append(server.get_clipboard_subsystem_class())
    if features.pulseaudio:
        from xpra.server.subsystem.pulseaudio import PulseaudioServer
        classes.append(PulseaudioServer)
    if features.audio:
        from xpra.server.subsystem.audio import AudioServer
        classes.append(AudioServer)
    if features.encoding:
        from xpra.server.subsystem.encoding import EncodingServer
        classes.append(EncodingServer)
    if features.display:
        classes.append(server.get_display_subsystem_class())
    if features.rfb:
        from xpra.server.rfb.server import RFBServer
        classes.append(RFBServer)
    if features.rdp:
        from xpra.server.rdp.server import RDPServer
        classes.append(RDPServer)
    if features.window:
        classes.append(server.get_window_subsystem_class())
    if features.keyboard:
        classes.append(server.get_keyboard_subsystem_class())
    if features.pointer:
        classes.append(server.get_pointer_subsystem_class())
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
    if features.bell:
        if bell_class := server.get_bell_subsystem_class():
            classes.append(bell_class)
    if features.x11 and features.systray:
        from xpra.x11.subsystem.systray import SystemTrayServer
        classes.append(SystemTrayServer)
    from xpra.server.subsystem.client_session import ClientSessionServer
    classes.append(ClientSessionServer)
    from xpra.server.subsystem.settings import SettingsServer
    classes.append(SettingsServer)
    from xpra.server.subsystem.shutdown import ShutdownServer
    classes.append(ShutdownServer)
    if features.cursor:
        classes.append(server.get_cursor_subsystem_class())
    if features.x11 and features.display:
        from xpra.x11.subsystem.xsettings import XSettingsServer
        classes.append(XSettingsServer)
    return tuple(classes)
