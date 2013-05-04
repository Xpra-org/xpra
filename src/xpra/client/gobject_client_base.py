# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gobject
gobject = import_gobject()

from xpra.log import Logger
log = Logger()

from xpra.client.client_base import XpraClientBase, DEFAULT_TIMEOUT, EXIT_TIMEOUT, EXIT_OK
from xpra.net.protocol import set_scheduler
set_scheduler(gobject)


class GObjectXpraClient(XpraClientBase, gobject.GObject):
    """
        Utility superclass for glib clients
    """

    def __init__(self):
        gobject.GObject.__init__(self)
        XpraClientBase.__init__(self)

    def init(self, opts):
        XpraClientBase.init(self, opts)
        self.install_signal_handlers()
        self.glib_init()
        self.gobject_init()

    def timeout_add(self, *args):
        return gobject.timeout_add(*args)

    def idle_add(self, *args):
        return gobject.idle_add(*args)

    def source_remove(self, *args):
        return gobject.source_remove(*args)


    def client_type(self):
        #overriden in subclasses!
        return "Python/GObject"

    def timeout(self, *args):
        log.warn("timeout!")

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        def noop(*args):
            log("ignoring packet: %s", args)
        #ignore the following packet types without error:
        for t in ["new-window", "new-override-redirect",
                  "draw", "cursor", "bell",
                  "notify_show", "notify_close",
                  "ping", "ping_echo",
                  "window-metadata", "configure-override-redirect",
                  "lost-window"]:
            self._packet_handlers[t] = noop

    def gobject_init(self):
        try:
            gobject.threads_init()
        except AttributeError:
            #old versions of gobject may not have this method
            pass

    def connect_with_timeout(self, conn):
        self.setup_connection(conn)
        gobject.timeout_add(DEFAULT_TIMEOUT, self.timeout)
        gobject.idle_add(self.send_hello)

    def run(self):
        XpraClientBase.run(self)
        self.gobject_mainloop = gobject.MainLoop()
        self.gobject_mainloop.run()
        return  self.exit_code

    def make_hello(self, challenge_response=None):
        capabilities = XpraClientBase.make_hello(self, challenge_response)
        capabilities["keyboard"] = False
        return capabilities

    def quit(self, exit_code):
        log("quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        self.cleanup()
        gobject.timeout_add(50, self.gobject_mainloop.quit)



class CommandConnectClient(GObjectXpraClient):
    """
        Utility superclass for clients that only send one command.
    """

    def __init__(self, conn, opts):
        GObjectXpraClient.__init__(self)
        GObjectXpraClient.init(self, opts)
        self.connect_with_timeout(conn)


class ScreenshotXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, conn, opts, screenshot_filename):
        self.screenshot_filename = screenshot_filename
        CommandConnectClient.__init__(self, conn, opts)

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the screenshot")

    def _process_screenshot(self, packet):
        (w, h, encoding, _, img_data) = packet[1:6]
        assert encoding=="png"
        if len(img_data)==0:
            self.warn_and_quit(EXIT_OK, "screenshot is empty and has not been saved (maybe there are no windows or they are not currently shown)")
            return
        f = open(self.screenshot_filename, 'wb')
        f.write(img_data)
        f.close()
        self.warn_and_quit(EXIT_OK, "screenshot %sx%s saved to: %s" % (w, h, self.screenshot_filename))

    def init_packet_handlers(self):
        GObjectXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["screenshot"] = self._process_screenshot

    def make_hello(self, challenge_response=None):
        capabilities = GObjectXpraClient.make_hello(self, challenge_response)
        capabilities["screenshot_request"] = True
        return capabilities


class InfoXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")

    def _process_hello(self, packet):
        log.debug("process_hello: %s", packet)
        props = packet[1]
        if props:
            for k in sorted(props.keys()):
                v = props.get(k)
                log.info("%s=%s", k, v)
        self.quit(0)

    def make_hello(self, challenge_response=None):
        capabilities = GObjectXpraClient.make_hello(self, challenge_response)
        log.debug("make_hello(%s) adding info_request to %s", challenge_response, capabilities)
        capabilities["info_request"] = True
        return capabilities


class VersionXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server for version information and prints it out
    """

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the version")

    def _process_hello(self, packet):
        log.debug("process_hello: %s", packet)
        props = packet[1]
        self.warn_and_quit(EXIT_OK, str(props.get("version")))

    def make_hello(self, challenge_response=None):
        capabilities = GObjectXpraClient.make_hello(self, challenge_response)
        log.debug("make_hello(%s) adding version_request to %s", challenge_response, capabilities)
        capabilities["version_request"] = True
        return capabilities


class StopXpraClient(CommandConnectClient):
    """ stop a server """

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not disconnect us")

    def _process_hello(self, packet):
        gobject.idle_add(self.send, "shutdown-server")
