# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gobject, import_glib
gobject = import_gobject()
glib = import_glib()

from xpra.log import Logger
log = Logger("gobject", "client")

import sys
from xpra.util import nonl, sorted_nicely, print_nested_dict, envbool, DONE
from xpra.os_util import bytestostr, get_hex_uuid
from xpra.client.client_base import XpraClientBase, EXTRA_TIMEOUT
from xpra.exit_codes import (EXIT_OK, EXIT_TIMEOUT, EXIT_INTERNAL_ERROR, EXIT_FAILURE, EXIT_UNSUPPORTED, EXIT_REMOTE_ERROR, EXIT_FILE_TOO_BIG)

FLATTEN_INFO = envbool("XPRA_FLATTEN_INFO", True)


class GObjectXpraClient(XpraClientBase, gobject.GObject):
    """
        Utility superclass for GObject clients
    """
    INSTALL_SIGNAL_HANDLERS = True

    def __init__(self):
        gobject.GObject.__init__(self)
        XpraClientBase.__init__(self)

    def init(self, opts):
        XpraClientBase.init(self, opts)
        if self.INSTALL_SIGNAL_HANDLERS:
            self.install_signal_handlers()
        self.glib_init()
        self.gobject_init()

    def timeout_add(self, *args):
        return glib.timeout_add(*args)

    def idle_add(self, *args):
        return glib.idle_add(*args)

    def source_remove(self, *args):
        return glib.source_remove(*args)

    def get_scheduler(self):
        return glib


    def client_type(self):
        #overriden in subclasses!
        return "Python%s/GObject" % sys.version_info[0]

    def timeout(self, *args):
        log.warn("timeout!")

    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        def noop(*args):
            log("ignoring packet: %s", args)
        #ignore the following packet types without error:
        #(newer servers should avoid sending us any of those)
        for t in ["new-window", "new-override-redirect",
                  "draw", "cursor", "bell",
                  "notify_show", "notify_close",
                  "ping", "ping_echo",
                  "window-metadata", "configure-override-redirect",
                  "lost-window"]:
            self._packet_handlers[t] = noop

    def gobject_init(self):
        gobject.threads_init()

    def run(self):
        XpraClientBase.run(self)
        self.glib_mainloop = glib.MainLoop()
        self.glib_mainloop.run()
        return  self.exit_code

    def make_hello(self):
        capabilities = XpraClientBase.make_hello(self)
        capabilities["keyboard"] = False
        return capabilities

    def quit(self, exit_code):
        log("quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        self.cleanup()
        glib.timeout_add(50, self.glib_mainloop.quit)



class CommandConnectClient(GObjectXpraClient):
    """
        Utility superclass for clients that only send one command
        via the hello packet.
    """
    COMMAND_TIMEOUT = EXTRA_TIMEOUT

    def __init__(self, conn, opts):
        GObjectXpraClient.__init__(self)
        GObjectXpraClient.init(self, opts)
        connection, display_desc = conn
        self.display_desc = display_desc
        self.connect_with_timeout(connection)
        self._protocol._log_stats  = False
        #not used by command line clients,
        #so don't try probing for printers, etc
        self.file_transfer = False
        self.printing = False
        #don't bother with many of these things for one-off commands:
        for x in ("ui_client", "wants_aliases", "wants_encodings",
                  "wants_versions", "wants_features", "wants_sound", "windows"):
            self.hello_extra[x] = False

    def connect_with_timeout(self, conn):
        self.setup_connection(conn)
        if conn.timeout>0:
            glib.timeout_add((conn.timeout + self.COMMAND_TIMEOUT) * 1000, self.timeout)
        glib.idle_add(self.send_hello)

    def _process_connection_lost(self, packet):
        #override so we don't log a warning
        #"command clients" are meant to exit quickly by losing the connection
        self.quit(EXIT_OK)

    def server_connection_established(self):
        #don't bother parsing the network caps:
        #* it could cause errors if the caps are missing
        #* we don't care about sending anything back after hello
        log("server_capabilities: %s", self.server_capabilities)
        log("protocol state: %s", self._protocol.save_state())
        self.do_command()

    def do_command(self):
        raise NotImplementedError()


class SendCommandConnectClient(CommandConnectClient):
    """
        Utility superclass for clients that only send at least one more packet
        after the hello packet.
        So unlike CommandConnectClient, we do need the network and encryption to be setup.
    """

    def server_connection_established(self):
        assert self.parse_encryption_capabilities(), "encryption failure"
        assert self.parse_network_capabilities(), "network capabilities failure"
        CommandConnectClient.server_connection_established(self)


class HelloRequestClient(SendCommandConnectClient):
    """
        Utility superclass for clients that send a server request
        as part of the hello packet.
    """

    def make_hello_base(self):
        caps = CommandConnectClient.make_hello_base(self)
        caps.update(self.hello_request())
        return caps

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not disconnect us")

    def hello_request(self):
        raise NotImplementedError()

    def do_command(self):
        self.quit(EXIT_OK)


class ScreenshotXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, conn, opts, screenshot_filename):
        self.screenshot_filename = screenshot_filename
        CommandConnectClient.__init__(self, conn, opts)
        self.hello_extra["screenshot_request"] = True

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the screenshot")

    def _process_screenshot(self, packet):
        (w, h, encoding, _, img_data) = packet[1:6]
        assert encoding=="png"
        if len(img_data)==0:
            self.warn_and_quit(EXIT_OK, "screenshot is empty and has not been saved (maybe there are no windows or they are not currently shown)")
            return
        with open(self.screenshot_filename, 'wb') as f:
            f.write(img_data)
        self.warn_and_quit(EXIT_OK, "screenshot %sx%s saved to: %s" % (w, h, self.screenshot_filename))

    def init_packet_handlers(self):
        GObjectXpraClient.init_packet_handlers(self)
        self._ui_packet_handlers["screenshot"] = self._process_screenshot


class InfoXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, *args):
        CommandConnectClient.__init__(self, *args)
        self.hello_extra["info_request"] = True
        if FLATTEN_INFO!=1:
            self.hello_extra["info-namespace"] = True

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")

    def do_command(self):
        if self.server_capabilities:
            if FLATTEN_INFO<2:
                #compatibility mode:
                for k in sorted_nicely(self.server_capabilities.keys()):
                    v = self.server_capabilities.get(k)
                    if sys.version_info[0]>=3:
                        #FIXME: this is a nasty and horrible python3 workaround (yet again)
                        #we want to print bytes as strings without the ugly 'b' prefix..
                        #it assumes that all the strings are raw or in (possibly nested) lists or tuples only
                        def fixvalue(w):
                            if type(w)==bytes:
                                return bytestostr(w)
                            elif type(w) in (tuple,list):
                                return type(w)([fixvalue(x) for x in w])
                            return w
                        v = fixvalue(v)
                    log.info("%s=%s", bytestostr(k), nonl(v))
            else:
                print_nested_dict(self.server_capabilities)
        self.quit(EXIT_OK)


class ConnectTestXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, *args):
        CommandConnectClient.__init__(self, *args)
        self.value = get_hex_uuid()
        self.hello_extra.update({
            "connect_test_request"     : self.value,
            #older servers don't know about connect-test,
            #pretend that we're interested in info:
            "info_request"             : True,
            "info-namespace"           : True,
            })

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: no server response")

    def _process_connection_lost(self, packet):
        #we should always receive a hello back and call do_command,
        #which sets the correct exit code, landing here is an error:
        self.quit(EXIT_FAILURE)

    def do_command(self):
        if self.server_capabilities:
            ctr = self.server_capabilities.get("connect_test_response")
            log("do_command() expected connect test response='%s', got '%s'", self.value, ctr)
            if ctr==self.value:
                self.quit(EXIT_OK)
            else:
                self.quit(EXIT_INTERNAL_ERROR)
        else:
            self.quit(EXIT_FAILURE)


class MonitorXpraClient(SendCommandConnectClient):
    """ This client does one thing only:
        it prints out events received from the server.
        If the server does not support this feature it exits with an error.
    """

    def __init__(self, *args):
        SendCommandConnectClient.__init__(self, *args)
        for x in ("wants_features", "wants_events", "event_request"):
            self.hello_extra[x] = True

    def timeout(self, *args):
        pass
        #self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")

    def do_command(self):
        log.info("waiting for server events")

    def _process_server_event(self, packet):
        log.info(": ".join(packet[1:]))

    def init_packet_handlers(self):
        SendCommandConnectClient.init_packet_handlers(self)
        self._packet_handlers["server-event"] = self._process_server_event
        self._packet_handlers["ping"] = self._process_ping

    def _process_ping(self, packet):
        echotime = packet[1]
        self.send("ping_echo", echotime, 0, 0, 0, -1)


class VersionXpraClient(HelloRequestClient):
    """ This client does one thing only:
        it queries the server for version information and prints it out
    """

    def hello_request(self):
        return {"version_request" : True}

    def do_command(self):
        v = self.server_capabilities.get("version")
        if not v:
            self.warn_and_quit(EXIT_FAILURE, "server did not provide the version information")
        else:
            sys.stdout.write("%s\n" % (v,))
            self.quit(EXIT_OK)


class ControlXpraClient(CommandConnectClient):
    """ Allows us to send commands to a server.
    """
    def set_command_args(self, command):
        self.command = command

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not respond")

    def do_command(self):
        cr = self.server_capabilities.listget("command_response")
        if cr is None:
            self.warn_and_quit(EXIT_UNSUPPORTED, "server does not support control command")
            return
        code, text = cr
        text = bytestostr(text)
        if code!=0:
            log.warn("server returned error code %s", code)
            self.warn_and_quit(EXIT_REMOTE_ERROR, " %s" % text)
            return
        self.warn_and_quit(EXIT_OK, text)

    def make_hello(self):
        capabilities = GObjectXpraClient.make_hello(self)
        log("make_hello() adding command request '%s' to %s", self.command, capabilities)
        capabilities["command_request"] = self.command
        return capabilities


class PrintClient(SendCommandConnectClient):
    """ Allows us to send a file to the server for printing.
    """
    def set_command_args(self, command):
        log("set_command_args(%s)", command)
        self.filename = command[0]
        #print command arguments:
        #filename, file_data, mimetype, source_uuid, title, printer, no_copies, print_options_str = packet[1:9]
        self.command = command[1:]
        #TODO: load as needed...
        def sizeerr(size):
            self.warn_and_quit(EXIT_FILE_TOO_BIG, "the file is too large: %iMB (the file size limit is %iMB)" % (size//1024//1024, self.file_size_limit))
            return
        if self.filename=="-":
            #replace with filename proposed
            self.filename = command[2]
            #read file from stdin
            self.file_data = sys.stdin.read()
            log("read %i bytes from stdin", len(self.file_data))
        else:
            import os.path
            size = os.path.getsize(self.filename)
            if size>self.file_size_limit*1024*1024:
                sizeerr(size)
                return
            from xpra.os_util import load_binary_file
            self.file_data = load_binary_file(self.filename)
            log("read %i bytes from %s", len(self.file_data), self.filename)
        size = len(self.file_data)
        if size>self.file_size_limit*1024*1024:
            sizeerr(size)
            return
        assert self.file_data, "no data found for '%s'" % self.filename

    def client_type(self):
        return "Python/GObject/Print"

    def timeout(self, *args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not respond")

    def do_command(self):
        printing = self.server_capabilities.boolget("printing")
        if not printing:
            self.warn_and_quit(EXIT_UNSUPPORTED, "server does not support printing")
            return
        #TODO: compress file data? (this should run locally most of the time anyway)
        from xpra.net.compression import Compressed
        blob = Compressed("print", self.file_data)
        self.send("print", self.filename, blob, *self.command)
        log("print: sending %s as %s for printing", self.filename, blob)
        self.idle_add(self.send, "disconnect", DONE, "detaching")

    def make_hello(self):
        capabilities = SendCommandConnectClient.make_hello(self)
        capabilities["wants_features"] = True   #so we know if printing is supported or not
        capabilities["print_request"] = True    #marker to skip full setup
        return capabilities


class ExitXpraClient(HelloRequestClient):
    """ This client does one thing only:
        it asks the server to terminate (like stop),
        but without killing the Xvfb or clients.
    """

    def hello_request(self):
        return {"exit_request" : True}

    def do_command(self):
        self.idle_add(self.send, "exit-server")


class StopXpraClient(HelloRequestClient):
    """ stop a server """

    def hello_request(self):
        return {"stop_request"  : True}

    def do_command(self):
        if not self.can_shutdown_server:
            log.error("Error: cannot shutdown this server")
            log.error(" the feature is disable on the server")
            self.quit(EXIT_FAILURE)
            return
        self.idle_add(self.send_shutdown_server)
        #not exiting the client here,
        #the server should send us the shutdown disconnection message anyway
        #and if not, we will then hit the timeout to tell us something went wrong


class DetachXpraClient(HelloRequestClient):
    """ run the detach subcommand """

    def hello_request(self):
        return {"detach_request" : True}

    def do_command(self):
        self.idle_add(self.send, "disconnect", DONE, "detaching")
        #not exiting the client here,
        #the server should disconnect us with the response

class RequestStartClient(HelloRequestClient):
    """ request the system proxy server to start a new session for us """
    #wait longer for this command to return:
    from xpra.scripts.main import WAIT_SERVER_TIMEOUT
    COMMAND_TIMEOUT = EXTRA_TIMEOUT+WAIT_SERVER_TIMEOUT

    def hello_request(self):
        return {"start-new-session" : self.start_new_session}

    def server_connection_established(self):
        #the server should respond with the display chosen
        log("server_connection_established() exit_code=%s", self.exit_code)
        display = self.server_capabilities.get("display")
        if display:
            try:
                sys.stderr.write("session now available on display %s\n" % display)
                sys.stderr.flush()
            except:
                pass
        if not self.exit_code:
            self.quit(0)
