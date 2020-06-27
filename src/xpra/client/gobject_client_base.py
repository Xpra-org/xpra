# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from gi.repository import GLib
from gi.repository import GObject

from xpra.util import (
    nonl, sorted_nicely, print_nested_dict, envint, flatten_dict, typedict,
    disconnect_is_an_error, ellipsizer, DONE, first_time,
    )
from xpra.os_util import bytestostr, get_hex_uuid, POSIX, OSX, hexstr
from xpra.client.client_base import XpraClientBase, EXTRA_TIMEOUT
from xpra.exit_codes import (
    EXIT_OK, EXIT_CONNECTION_LOST, EXIT_TIMEOUT, EXIT_INTERNAL_ERROR,
    EXIT_FAILURE, EXIT_UNSUPPORTED, EXIT_REMOTE_ERROR, EXIT_FILE_TOO_BIG,
    )
from xpra.log import Logger

log = Logger("gobject", "client")

FLATTEN_INFO = envint("XPRA_FLATTEN_INFO", 1)


def errwrite(msg):
    try:
        sys.stderr.write(msg)
        sys.stderr.flush()
    except (OSError, AttributeError):
        pass


class GObjectXpraClient(GObject.GObject, XpraClientBase):
    """
        Utility superclass for GObject clients
    """
    COMMAND_TIMEOUT = EXTRA_TIMEOUT

    def __init__(self):
        self.idle_add = GLib.idle_add
        self.timeout_add = GLib.timeout_add
        self.source_remove = GLib.source_remove
        GObject.GObject.__init__(self)
        XpraClientBase.__init__(self)

    def init(self, opts):
        XpraClientBase.init(self, opts)
        self.glib_init()

    def get_scheduler(self):
        return GLib


    def install_signal_handlers(self):
        #only register the glib signal handler
        #once the main loop is running,
        #before that we just trigger a KeyboardInterrupt
        def do_install_signal_handlers():
            sstr = "%s Client" % self.client_type()
            from xpra.gtk_common.gobject_compat import register_os_signals, register_SIGUSR_signals
            register_os_signals(self.handle_app_signal, sstr)
            register_SIGUSR_signals(sstr)
        GLib.idle_add(do_install_signal_handlers)


    def setup_connection(self, conn):
        protocol = super().setup_connection(conn)
        protocol._log_stats  = False
        GLib.idle_add(self.send_hello)
        return protocol


    def client_type(self):
        #overriden in subclasses!
        return "Python3/GObject"


    def init_packet_handlers(self):
        XpraClientBase.init_packet_handlers(self)
        def noop(*args):    # pragma: no cover
            log("ignoring packet: %s", args)
        #ignore the following packet types without error:
        #(newer servers should avoid sending us any of those)
        for t in (
            "new-window", "new-override-redirect",
            "draw", "cursor", "bell",
            "notify_show", "notify_close",
            "ping", "ping_echo",
            "window-metadata", "configure-override-redirect",
            "lost-window",
            ):
            self._packet_handlers[t] = noop

    def run(self):
        XpraClientBase.run(self)
        self.glib_mainloop = GLib.MainLoop()
        self.glib_mainloop.run()
        return self.exit_code

    def make_hello(self):
        capabilities = XpraClientBase.make_hello(self)
        capabilities["keyboard"] = False
        return capabilities

    def quit(self, exit_code):
        log("quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        self.cleanup()
        GLib.timeout_add(50, self.glib_mainloop.quit)



class CommandConnectClient(GObjectXpraClient):
    """
        Utility superclass for clients that only send one command
        via the hello packet.
    """

    def __init__(self, opts):
        super().__init__()
        super().init(opts)
        self.display_desc = {}
        #not used by command line clients,
        #so don't try probing for printers, etc
        self.file_transfer = False
        self.printing = False
        #don't bother with many of these things for one-off commands:
        for x in ("ui_client", "wants_aliases", "wants_encodings",
                  "wants_versions", "wants_features", "wants_sound", "windows",
                  "webcam", "keyboard", "mouse", "network-state",
                  ):
            self.hello_extra[x] = False

    def setup_connection(self, conn):
        protocol = super().setup_connection(conn)
        if conn.timeout>0:
            GLib.timeout_add((conn.timeout + self.COMMAND_TIMEOUT) * 1000, self.timeout)
        return protocol

    def timeout(self, *_args):
        log.warn("timeout!")    # pragma: no cover


    def _process_connection_lost(self, _packet):
        #override so we don't log a warning
        #"command clients" are meant to exit quickly by losing the connection
        p = self._protocol
        if p and p.input_packetcount==0:
            self.quit(EXIT_CONNECTION_LOST)
        else:
            self.quit(EXIT_OK)

    def server_connection_established(self, caps : typedict):
        #don't bother parsing the network caps:
        #* it could cause errors if the caps are missing
        #* we don't care about sending anything back after hello
        log("server_capabilities: %s", ellipsizer(caps))
        log("protocol state: %s", self._protocol.save_state())
        self.do_command(caps)
        return True

    def do_command(self, caps : typedict):
        raise NotImplementedError()


class SendCommandConnectClient(CommandConnectClient):
    """
        Utility superclass for clients that only send at least one more packet
        after the hello packet.
        So unlike CommandConnectClient, we do need the network and encryption to be setup.
    """

    def server_connection_established(self, caps):
        assert self.parse_encryption_capabilities(caps), "encryption failure"
        assert self.parse_network_capabilities(caps), "network capabilities failure"
        return super().server_connection_established(caps)


class HelloRequestClient(SendCommandConnectClient):
    """
        Utility superclass for clients that send a server request
        as part of the hello packet.
    """

    def make_hello_base(self):
        caps = super().make_hello_base()
        caps.update(self.hello_request())
        return caps

    def timeout(self, *_args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not disconnect us")

    def hello_request(self):        # pragma: no cover
        raise NotImplementedError()

    def do_command(self, caps : typedict):
        self.quit(EXIT_OK)

    def _process_disconnect(self, packet):
        #overriden method so we can avoid printing a warning,
        #we haven't received the hello back from the server
        #but that's fine for a request client
        info = tuple(nonl(bytestostr(x)) for x in packet[1:])
        reason = info[0]
        if disconnect_is_an_error(reason):
            self.server_disconnect_warning(*info)
        elif self.exit_code is None:
            #we're not in the process of exiting already,
            #tell the user why the server is disconnecting us
            self.server_disconnect(*info)


class ScreenshotXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, opts, screenshot_filename):
        self.screenshot_filename = screenshot_filename
        super().__init__(opts)
        self.hello_extra["screenshot_request"] = True
        self.hello_extra["request"] = "screenshot"

    def timeout(self, *_args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the screenshot")

    def _process_screenshot(self, packet):
        (w, h, encoding, _, img_data) = packet[1:6]
        assert encoding==b"png", "expected png screenshot data but got %s" % bytestostr(encoding)
        if not img_data:
            self.warn_and_quit(EXIT_OK,
                               "screenshot is empty and has not been saved (maybe there are no windows or they are not currently shown)")
            return
        with open(self.screenshot_filename, 'wb') as f:
            f.write(img_data)
        self.warn_and_quit(EXIT_OK, "screenshot %sx%s saved to: %s" % (w, h, self.screenshot_filename))

    def init_packet_handlers(self):
        super().init_packet_handlers()
        self._ui_packet_handlers["screenshot"] = self._process_screenshot


class InfoXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, opts):
        super().__init__(opts)
        self.hello_extra["info_request"] = True
        self.hello_extra["request"] = "info"
        if FLATTEN_INFO>=1:
            self.hello_extra["info-namespace"] = True

    def timeout(self, *_args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")

    def do_command(self, caps : typedict):
        if caps:
            if FLATTEN_INFO<2:
                #compatibility mode:
                c = flatten_dict(caps)
                for k in sorted_nicely(c.keys()):
                    v = c.get(k)
                    #FIXME: this is a nasty and horrible python3 workaround (yet again)
                    #we want to print bytes as strings without the ugly 'b' prefix..
                    #it assumes that all the strings are raw or in (possibly nested) lists or tuples only
                    #we assume that all strings we get are utf-8,
                    #and fallback to the bytestostr hack if that fails
                    def fixvalue(w):
                        if isinstance(w, bytes):
                            if k.endswith(".data"):
                                return hexstr(w)
                            try:
                                return w.decode("utf-8")
                            except:
                                return bytestostr(w)
                        elif isinstance(w, (tuple,list)):
                            return type(w)([fixvalue(x) for x in w])
                        return w
                    v = fixvalue(v)
                    k = fixvalue(k)
                    log.info("%s=%s", k, nonl(v))
            else:
                print_nested_dict(caps)
        self.quit(EXIT_OK)

class IDXpraClient(InfoXpraClient):

    def __init__(self, *args):
        super().__init__(*args)
        self.hello_extra["request"] = "id"


class ConnectTestXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, opts, **kwargs):
        super().__init__(opts)
        self.value = get_hex_uuid()
        self.hello_extra.update({
            "connect_test_request"      : self.value,
            "request"                   : "connect_test",
            #tells proxy servers we don't want to connect to the real / new instance:
            "connect"                   : False,
            #older servers don't know about connect-test,
            #pretend that we're interested in info:
            "info_request"              : True,
            "info-namespace"            : True,
            })
        self.hello_extra.update(kwargs)

    def timeout(self, *_args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: no server response")

    def _process_connection_lost(self, _packet):
        #we should always receive a hello back and call do_command,
        #which sets the correct exit code, landing here is an error:
        self.quit(EXIT_FAILURE)

    def do_command(self, caps : typedict):
        if caps:
            ctr = caps.strget("connect_test_response")
            log("do_command(..) expected connect test response='%s', got '%s'", self.value, ctr)
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

    def __init__(self, opts):
        super().__init__(opts)
        for x in ("wants_features", "wants_events", "event_request"):
            self.hello_extra[x] = True
        self.hello_extra["request"] = "event"
        self.hello_extra["info-namespace"] = True

    def timeout(self, *args):
        pass
        #self.warn_and_quit(EXIT_TIMEOUT, "timeout: did not receive the info")

    def do_command(self, caps : typedict):
        log.info("waiting for server events")

    def _process_server_event(self, packet):
        log.info(": ".join(bytestostr(x) for x in packet[1:]))

    def init_packet_handlers(self):
        super().init_packet_handlers()
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
        return {
            "version_request"       : True,
            "request"               : "version",
            "full-version-request"  : True,
            }

    def parse_network_capabilities(self, *_args):
        #don't bother checking anything - this could generate warnings
        return True

    def do_command(self, caps : typedict):
        v = caps.strget(b"version")
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

    def timeout(self, *_args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not respond")

    def do_command(self, caps : typedict):
        cr = caps.tupleget("command_response")
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
        capabilities = super().make_hello()
        log("make_hello() adding command request '%s' to %s", self.command, capabilities)
        capabilities["command_request"] = self.command
        capabilities["request"] = "command"
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
            self.warn_and_quit(EXIT_FILE_TOO_BIG,
                               "the file is too large: %iMB (the file size limit is %iMB)" % (size//1024//1024, self.file_size_limit))
            return
        if self.filename=="-":
            #replace with filename proposed
            self.filename = command[2]
            #read file from stdin
            with open(sys.stdin.fileno(), mode='rb', closefd=False) as stdin_binary:
                self.file_data = stdin_binary.read()
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

    def timeout(self, *_args):
        self.warn_and_quit(EXIT_TIMEOUT, "timeout: server did not respond")

    def do_command(self, caps : typedict):
        printing = caps.boolget("printing")
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
        capabilities = super().make_hello()
        capabilities["wants_features"] = True   #so we know if printing is supported or not
        capabilities["print_request"] = True    #marker to skip full setup
        capabilities["request"] = "print"
        return capabilities


class ExitXpraClient(HelloRequestClient):
    """ This client does one thing only:
        it asks the server to terminate (like stop),
        but without killing the Xvfb or clients.
    """

    def hello_request(self):
        return {
            "exit_request"  : True,
            "request"       : "exit",
            }

    def do_command(self, caps : typedict):
        self.idle_add(self.send, "exit-server")


class StopXpraClient(HelloRequestClient):
    """ stop a server """

    def hello_request(self):
        return {
            "stop_request"  : True,
            "request"       : "stop",
            }

    def do_command(self, caps : typedict):
        if not self.server_client_shutdown:
            log.error("Error: cannot shutdown this server")
            log.error(" the feature is disable on the server")
            self.quit(EXIT_FAILURE)
            return
        self.timeout_add(1000, self.send_shutdown_server)
        #self.idle_add(self.send_shutdown_server)
        #not exiting the client here,
        #the server should send us the shutdown disconnection message anyway
        #and if not, we will then hit the timeout to tell us something went wrong


class DetachXpraClient(HelloRequestClient):
    """ run the detach subcommand """

    def hello_request(self):
        return {
            "detach_request"    : True,
            "request"           : "detach",
            }

    def do_command(self, caps : typedict):
        self.idle_add(self.send, "disconnect", DONE, "detaching")
        #not exiting the client here,
        #the server should disconnect us with the response

class WaitForDisconnectXpraClient(DetachXpraClient):
    """ we just want the connection to close """

    def _process_disconnect(self, _packet):
        self.quit(EXIT_OK)


class RequestStartClient(HelloRequestClient):
    """ request the system proxy server to start a new session for us """
    #wait longer for this command to return:
    from xpra.scripts.main import WAIT_SERVER_TIMEOUT
    COMMAND_TIMEOUT = EXTRA_TIMEOUT+WAIT_SERVER_TIMEOUT

    def dots(self):
        errwrite(".")
        return not self.connection_established

    def _process_connection_lost(self, packet):
        errwrite("\n")
        super()._process_connection_lost(packet)

    def hello_request(self):
        if first_time("hello-request"):
            #this can be called again if we receive a challenge,
            #but only print this message once:
            errwrite("requesting new session, please wait")
        self.timeout_add(1*1000, self.dots)
        return {
            "start-new-session" : self.start_new_session,
            #tells proxy servers we don't want to connect to the real / new instance:
            "connect"                   : False,
            }

    def server_connection_established(self, caps : typedict):
        #the server should respond with the display chosen
        log("server_connection_established() exit_code=%s", self.exit_code)
        display = caps.strget("display")
        if display:
            mode = caps.strget("mode")
            session_type = {
                "start"         : "seamless ",
                "start-desktop" : "desktop ",
                "shadow"        : "shadow ",
                }.get(mode, "")
            try:
                errwrite("\n%ssession now available on display %s\n" % (session_type, display))
                if POSIX and not OSX and self.displayfd>0 and display and display.startswith(b":"):
                    from xpra.platform.displayfd import write_displayfd
                    log("writing display %s to displayfd=%s", display, self.displayfd)
                    write_displayfd(self.displayfd, display[1:])
            except OSError:
                log("server_connection_established(..)", exc_info=True)
        if not self.exit_code:
            self.quit(0)
        return True

    def __init__(self, opts):
        super().__init__(opts)
        try:
            self.displayfd = int(opts.displayfd)
        except (ValueError, TypeError):
            self.displayfd = 0
