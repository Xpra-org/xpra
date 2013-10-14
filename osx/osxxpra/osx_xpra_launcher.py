#!/usr/bin/env python

from xpra.client.gtk_base.client_launcher import main

#force py2app to include all those:
from xpra.platform.darwin.shadow_server import ShadowServer
from xpra.platform.darwin.features import CAN_DAEMONIZE
from xpra.platform.darwin.gui import get_OSXApplication
from xpra.platform.darwin.info import get_sys_info
from xpra.platform.darwin.keyboard import Keyboard
from xpra.platform.darwin.options import add_client_options
from xpra.platform.darwin.osx_menu import getOSXMenuHelper
from xpra.platform.darwin.osx_tray import OSXTray
from xpra.platform.darwin.osx_clipboard import OSXClipboardProtocolHelper
from xpra.platform.darwin.paths import get_resources_dir
from xpra.client.gl.gl_client_window import GLClientWindow
from xpra.client.gtk2.client import XpraClient
from xpra.gtk_common.gtk_view_clipboard import ClipboardStateInfoWindow
from xpra.gtk_common.gtk_view_keyboard import KeyboardStateInfoWindow

main()
