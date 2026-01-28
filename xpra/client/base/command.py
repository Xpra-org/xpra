# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import sys
from time import monotonic
from typing import Any
from collections.abc import Sequence

from xpra.util.objects import typedict
from xpra.util.str_fn import csv, Ellipsizer, repr_ellipsized, ellipsize, sorted_nicely, bytestostr, hexstr
from xpra.util.env import envint, first_time
from xpra.common import ConnectionMessage, disconnect_is_an_error, BACKWARDS_COMPATIBLE
from xpra.os_util import gi_import, get_hex_uuid, POSIX, OSX
from xpra.util.io import stderr_print, load_binary_file
from xpra.net.common import Packet, PacketElement
from xpra.util.stats import std_unit
from xpra.client.base.client import EXTRA_TIMEOUT
from xpra.client.base.gobject import GObjectXpraClient
from xpra.exit_codes import ExitCode, ExitValue, exit_str
from xpra.log import Logger

log = Logger("gobject", "client")

GLib = gi_import("GLib")


def errwrite(msg: str) -> None:
    stderr_print(msg)


class CommandConnectClient(GObjectXpraClient):
    """
        Utility superclass for clients that only send one command
        via the hello packet.
    """

    def __init__(self, opts):
        super().__init__()
        super().init(opts)
        self.display_desc = {}
        # not used by command line clients,
        # so don't try probing for printers, etc
        self.file_transfer = False
        self.printing = False
        self.command_timeout = None
        self.last_server_event: Sequence[PacketElement] = ()
        # don't bother with many of these things for one-off commands:
        SKIP = ["ui_client", "windows", "webcam", "keyboard", "pointer", "network-state"]
        if BACKWARDS_COMPATIBLE:
            SKIP.append("mouse")
        for x in SKIP:
            self.hello_extra[x] = False
        # for newer versions, it is easier:
        self.hello_extra["wants"] = []

    def make_protocol(self, conn):
        protocol = super().make_protocol(conn)
        if conn.timeout > 0:
            self.command_timeout = GLib.timeout_add((conn.timeout + self.COMMAND_TIMEOUT) * 1000, self.timeout)
        return protocol

    def timeout(self, *_args) -> None:
        log.warn("timeout!")  # pragma: no cover

    def cancel_command_timeout(self) -> None:
        ct = self.command_timeout
        if ct:
            self.command_timeout = None
            GLib.source_remove(ct)

    def _process_connection_lost(self, packet: Packet) -> None:
        log("_process_connection_lost%s", packet)
        # override so we don't log a warning
        # "command clients" are meant to exit quickly by losing the connection
        p = self._protocol
        if p and p.input_packetcount == 0:
            # never got any data back, so we have never connected,
            # try to give feedback to the user as to why that is:
            details = ""
            if len(packet) > 1:
                details = ": %s" % csv(packet[1:])
            log.warn("Connection failed%s", details)
            self.quit(ExitCode.CONNECTION_FAILED)
        else:
            self.quit(ExitCode.OK)

    def server_connection_established(self, caps: typedict) -> bool:
        # don't bother parsing the network caps:
        # * it could cause errors if the caps are missing
        # * we don't care about sending anything back after hello
        log("server_capabilities: %s", Ellipsizer(caps))
        log("protocol state: %s", self._protocol.save_state())
        self.init_authenticated_packet_handlers()
        self.cancel_command_timeout()
        self.do_command(caps)
        return True

    def do_command(self, caps: typedict) -> None:
        raise NotImplementedError(f"no do_command method in {self!r}")


class SendCommandConnectClient(CommandConnectClient):
    """
        Utility superclass for clients that only send at least one more packet
        after the hello packet.
        So unlike CommandConnectClient, we do need the network and encryption to be setup.
    """

    def server_connection_established(self, caps) -> bool:
        assert self.parse_network_capabilities(caps), "network capabilities failure"
        return super().server_connection_established(caps)

    def do_command(self, caps: typedict) -> None:
        raise NotImplementedError()


class HelloRequestClient(SendCommandConnectClient):
    """
        Utility superclass for clients that send a server request
        as part of the hello packet.
    """

    def make_hello_base(self) -> dict[str, Any]:
        return super().make_hello_base() | self.hello_request()

    def timeout(self, *_args) -> None:
        log("%s client reached the timeout", type(self))  # pragma: no cover
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: server did not disconnect us")

    def hello_request(self) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError(f"`hello_request` not implemented in {self!r}")

    def do_command(self, caps: typedict) -> None:
        self.quit(ExitCode.OK)

    def _process_disconnect(self, packet: Packet) -> None:
        # overridden method, so we can avoid printing a warning,
        # we haven't received the hello back from the server
        # but that's fine for a request client
        info = tuple(str(x) for x in packet[1:])
        reason = info[0]
        if disconnect_is_an_error(reason):
            self.server_disconnect_warning(*info)
        elif self.exit_code is None:
            # we're not in the process of exiting already,
            # tell the user why the server is disconnecting us
            self.server_disconnect(*info)


class ScreenshotXpraClient(HelloRequestClient):
    """ This client does one thing only:
        it sends the hello packet with a screenshot request
        and exits when the resulting image is received (or timedout)
    """

    def __init__(self, opts, screenshot_filename):
        self.screenshot_filename = screenshot_filename
        super().__init__(opts)

    def hello_request(self) -> dict[str, Any]:
        return {
            "request": "screenshot",
        }

    def do_command(self, caps: typedict) -> None:
        self.send("screenshot")

    def timeout(self, *_args) -> None:
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: did not receive the screenshot")

    def _process_screenshot(self, packet: Packet) -> None:
        w = packet.get_u16(1)
        h = packet.get_u16(2)
        encoding = packet.get_str(3)
        img_data = packet.get_buffer(5)
        assert encoding == "png", "expected png screenshot data but got %s" % encoding
        if not img_data:
            self.warn_and_quit(ExitCode.OK,
                               "screenshot is empty and has not been saved"
                               " (maybe there are no windows or they are not currently shown)")
            return
        if self.screenshot_filename == "-":
            output = os.fdopen(sys.stdout.fileno(), "wb", closefd=False)
        else:
            output = open(self.screenshot_filename, "wb")
        with output:
            output.write(img_data)
            output.flush()
        self.warn_and_quit(ExitCode.OK, f"screenshot {w}x{h} saved to: {self.screenshot_filename!r}")

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("screenshot")


class InfoXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, opts, subsystems: Sequence[str] = ()):
        super().__init__(opts)
        self.hello_extra["request"] = "info"
        if subsystems:
            self.hello_extra["subsystems"] = subsystems
        log("info request for subsystems %s", subsystems or "'all'")

    def timeout(self, *_args):
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: did not receive the info")

    def do_command(self, caps: typedict) -> None:
        if not caps:
            self.quit(ExitCode.NO_DATA)
            return

        LINE_LIMIT = envint("XPRA_INFO_LINE_LIMIT", 320)

        def print_fn(s) -> None:
            sys.stdout.write(f"{s}\n")

        def prettify(k, v) -> str:
            ks = str(k)
            if ks.endswith("xid"):
                try:
                    return hex(int(v))
                except (TypeError, ValueError):
                    pass
            if ks.endswith("version") and isinstance(v, (tuple, list)):
                return ".".join(str(x) for x in v)
            if isinstance(v, bytes):
                if ks.endswith(".data"):
                    return hexstr(v)
                return bytestostr(v)
            elif isinstance(v, (int, bool, float)):
                return str(v)
            elif isinstance(v, (tuple, list)):
                eltypes = set(type(x) for x in v)
                if len(eltypes) == 1:
                    eltype = tuple(eltypes)[0]
                    if eltype in (int, bool, float):
                        return repr_ellipsized(v, LINE_LIMIT)
                    if eltype is str:
                        csv_str = csv(repr(x) for x in v)
                        return ellipsize(csv_str, LINE_LIMIT)
                return repr_ellipsized(type(v)(prettify(k, x) for x in v), LINE_LIMIT)
            elif isinstance(v, str) and v.isprintable():
                return v
            return repr_ellipsized(v, LINE_LIMIT)

        def print_dict(d: dict, path=""):
            for k in sorted_nicely(d.keys()):
                v = d.get(k)
                fk = prettify(k, k)
                kpath = f"{path}.{fk}".strip(".")
                if isinstance(v, dict):
                    print_dict(v, kpath)
                    continue
                fv = prettify(k, v)
                print_fn(f"{kpath}={fv}")

        exit_code = ExitCode.OK
        try:
            print_dict(dict(caps))
        except OSError:
            exit_code = ExitCode.IO_ERROR
        self.quit(exit_code)


class IDXpraClient(InfoXpraClient):

    def __init__(self, *args):
        super().__init__(*args)
        self.hello_extra["request"] = "id"


class RequestXpraClient(CommandConnectClient):

    def __init__(self, request, opts):
        super().__init__(opts)
        self.hello_extra["request"] = request

    def do_command(self, caps: typedict) -> None:
        self.quit(ExitCode.OK)


class ConnectTestXpraClient(CommandConnectClient):
    """ This client does one thing only:
        it queries the server with an 'info' request
    """

    def __init__(self, opts, **kwargs):
        super().__init__(opts)
        self.value = get_hex_uuid()
        self.hello_extra |= {
            "connect_test_request": self.value,
            "request": "connect_test",
            # tells proxy servers we don't want to connect to the real / new instance:
            "connect": False,
        }
        self.hello_extra.update(kwargs)

    def timeout(self, *_args) -> None:
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: no server response")

    def _process_connection_lost(self, _packet: Packet) -> None:
        # we should always receive a hello back and call do_command,
        # which sets the correct exit code, landing here is an error:
        self.quit(ExitCode.FAILURE)

    def do_command(self, caps: typedict) -> None:
        if caps:
            ctr = caps.strget("connect_test_response")
            log("do_command(..) expected connect test response='%s', got '%s'", self.value, ctr)
            if ctr == self.value:
                self.quit(ExitCode.OK)
            else:
                self.quit(ExitCode.INTERNAL_ERROR)
        else:
            self.quit(ExitCode.FAILURE)


class MonitorXpraClient(SendCommandConnectClient):
    """ This client does one thing only:
        it prints out events received from the server.
        If the server does not support this feature it exits with an error.
    """

    def __init__(self, opts):
        super().__init__(opts)
        for x in ("features", "events", "request"):
            self.hello_extra.setdefault("wants", []).append(x)
        self.hello_extra["request"] = "event"

    def timeout(self, *args) -> None:
        pass
        # self.warn_and_quit(ExitCode.TIMEOUT, "timeout: did not receive the info")

    def do_command(self, caps: typedict) -> None:
        log.info("waiting for server events")

    def _process_server_event(self, packet: Packet) -> None:
        log.info(": ".join(str(x) for x in packet[1:]))

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("server-event", "ping")

    def _process_ping(self, packet: Packet) -> None:
        echotime = packet.get_u64(1)
        self.send("ping_echo", echotime, 0, 0, 0, -1)


class InfoTimerClient(MonitorXpraClient):
    """
        This client keeps monitoring the server
        and requesting info data
    """
    REFRESH_RATE = envint("XPRA_REFRESH_RATE", 1)

    def __init__(self, *args):
        super().__init__(*args)
        self.info_request_pending = False
        self.server_last_info = typedict()
        self.server_last_info_time = 0
        self.info_timer = 0

    def run(self) -> ExitValue:
        from xpra.util.glib import register_os_signals
        register_os_signals(self.signal_handler, "")
        v = super().run()
        self.log("run()=%s" % v)
        self.cleanup()
        return v

    def signal_handler(self, signum: int, *args) -> None:
        self.log(f"exit_code={self.exit_code}")
        self.log(f"signal_handler({signum}, {args})")
        self.quit(128 + signum)
        self.log(f"exit_code={self.exit_code}")

    def log(self, message) -> None:
        # this method is overridden in top client to use a log file
        log(message)

    def err(self, e) -> None:
        log.error(str(e))

    def cleanup(self) -> None:
        self.cancel_info_timer()
        MonitorXpraClient.cleanup(self)

    def do_command(self, caps: typedict) -> None:
        self.send_info_request()
        GLib.timeout_add(self.REFRESH_RATE * 1000, self.send_info_request)

    def send_info_request(self, *categories: str) -> bool:
        self.log("send_info_request%s" % (categories,))
        if not self.info_request_pending:
            self.info_request_pending = True
            window_ids = ()  # no longer used or supported by servers
            self.send("info-request", [self.uuid], window_ids, categories)
        if not self.info_timer:
            self.info_timer = GLib.timeout_add((self.REFRESH_RATE + 2) * 1000, self.info_timeout)
        return True

    def init_packet_handlers(self) -> None:
        MonitorXpraClient.init_packet_handlers(self)
        self.add_packets("info-response")

    def _process_server_event(self, packet: Packet) -> None:
        self.log("server event: %s" % (packet,))
        self.last_server_event = packet[1:]
        self.update_screen()

    def _process_info_response(self, packet: Packet) -> None:
        self.log("info response: %s" % repr_ellipsized(packet))
        self.cancel_info_timer()
        self.info_request_pending = False
        self.server_last_info = typedict(packet.get_dict(1))
        self.server_last_info_time = monotonic()
        # log.info("server_last_info=%s", self.server_last_info)
        self.update_screen()

    def cancel_info_timer(self) -> None:
        it = self.info_timer
        if it:
            self.info_timer = 0
            GLib.source_remove(it)

    def info_timeout(self) -> bool:
        self.log("info timeout")
        self.update_screen()
        return True

    def update_screen(self) -> None:
        raise NotImplementedError()


def print_prompt() -> None:
    sys.stdout.write("> ")
    sys.stdout.flush()


class ShellXpraClient(SendCommandConnectClient):
    """
        Provides an interactive shell with the socket it connects to
    """

    def __init__(self, opts):
        super().__init__(opts)
        self.stdin_io_watch = None
        self.stdin_buffer = ""
        self.hello_extra["shell"] = "True"

    def timeout(self, *args) -> None:
        """
        The shell client never times out,
        but the superclass calls this method automatically,
        just ignore it.
        """

    def cleanup(self) -> None:
        siw = self.stdin_io_watch
        if siw:
            self.stdin_io_watch = None
            GLib.source_remove(siw)
        super().cleanup()

    def do_command(self, caps: typedict) -> None:
        if not caps.boolget("shell"):
            msg = "this server does not support the 'shell' subcommand"
            log.error(msg)
            self.disconnect_and_quit(ExitCode.UNSUPPORTED, msg)
            return
        # start reading from stdin:
        self.install_signal_handlers()
        stdin = sys.stdin
        fileno = stdin.fileno()
        import fcntl
        fl = fcntl.fcntl(fileno, fcntl.F_GETFL)
        fcntl.fcntl(fileno, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        self.stdin_io_watch = GLib.io_add_watch(sys.stdin,
                                                GLib.PRIORITY_DEFAULT, GLib.IO_IN,
                                                self.stdin_ready)
        print_prompt()

    def stdin_ready(self, *_args) -> bool:
        data = sys.stdin.read()
        # log.warn("stdin=%r", data)
        self.stdin_buffer += data
        sent = 0
        if self.stdin_buffer.endswith("\n"):
            for line in self.stdin_buffer.splitlines():
                if line:
                    if line.rstrip("\n\r") in ("quit", "exit"):
                        self.disconnect_and_quit(ExitCode.OK, "user requested %s" % line)
                        self.stdin_io_watch = None
                        return False
                    self.send("shell-exec", line.encode())
                    sent += 1
        self.stdin_buffer = ""
        if not sent:
            print_prompt()
        return True

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("shell-reply", "ping")

    def _process_ping(self, packet: Packet) -> None:
        echotime = packet.get_u64(1)
        self.send("ping_echo", echotime, 0, 0, 0, -1)

    @staticmethod
    def _process_shell_reply(packet: Packet) -> None:
        fd = packet.get_u8(1)
        message = packet.get_str(2)
        if fd == 1:
            stream = sys.stdout
        elif fd == 2:
            stream = sys.stderr
        else:
            raise ValueError(f"invalid file descriptor f{fd}")
        s = str(message)
        if s.endswith("\n"):
            s = s[:-1]
        stream.write(s)
        stream.flush()
        if fd == 2:
            stream.write("\n")
            print_prompt()


class VersionXpraClient(HelloRequestClient):
    """ This client does one thing only:
        it queries the server for version information and prints it out
    """

    def hello_request(self) -> dict[str, Any]:
        req: dict[str, Any] = {
            "request": "version",
        }
        if BACKWARDS_COMPATIBLE:
            req["full-version-request"] = True
        return req

    def parse_network_capabilities(self, *_args) -> bool:
        # don't bother checking anything - this could generate warnings
        return True

    def do_command(self, caps: typedict) -> None:
        v = caps.strget("version")
        if not v:
            self.warn_and_quit(ExitCode.FAILURE, "server did not provide the version information")
        else:
            sys.stdout.write(f"{v}\n")
            sys.stdout.flush()
            self.quit(ExitCode.OK)


class ControlXpraClient(CommandConnectClient):
    """ Allows us to send commands to a server.
    """
    def __init__(self, opts, command: Sequence[str]):
        super().__init__(opts)
        self.command = command

    def timeout(self, *_args) -> None:
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: server did not respond")

    def do_command(self, caps: typedict) -> None:
        cr = caps.tupleget("command_response")
        if not cr or len(cr) < 2:
            self.warn_and_quit(ExitCode.UNSUPPORTED, "server does not support control command")
            return
        code = int(cr[0])
        text = str(cr[1])
        if code != 0:
            log.warn("server returned error code %s", code)
            self.warn_and_quit(ExitCode.REMOTE_ERROR, " %s" % text)
            return
        self.warn_and_quit(ExitCode.OK, text)

    def make_hello(self) -> dict[str, Any]:
        capabilities = super().make_hello()
        log("make_hello() adding command request '%s' to %s", self.command, capabilities)
        capabilities["command_request"] = tuple(self.command)
        capabilities["request"] = "command"
        return capabilities


class RunClient(CommandConnectClient):
    """
    Requests the server to start a command
    """

    def __init__(self, opts, command: Sequence[str]):
        super().__init__(opts)
        self.command = command

    def timeout(self, *_args) -> None:
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: server did not respond")

    def do_command(self, caps: typedict) -> None:
        cr = typedict(caps.dictget("run_response") or {})
        if not cr:
            self.warn_and_quit(ExitCode.UNSUPPORTED, "server does not support run command")
            return
        code = cr.intget("code")
        pid = cr.intget("pid")
        message = cr.strget("message")
        if code != 0:
            log.warn("server returned error code %s: %s", code, exit_str(code))
            self.warn_and_quit(ExitCode.REMOTE_ERROR, " %s" % message)
            return
        sys.stdout.write(f"command started with pid {pid}\n")
        self.quit(ExitCode.OK)

    def make_hello(self) -> dict[str, Any]:
        capabilities = super().make_hello()
        log("make_hello() adding run request '%s' to %s", self.command, capabilities)
        capabilities["run"] = tuple(self.command)
        capabilities["request"] = "run"
        return capabilities


class PrintClient(SendCommandConnectClient):
    """
    Allows us to send a file to the server for printing.
    """

    def __init__(self, opts, command: Sequence[str]):
        super().__init__(opts)
        self.client_type = "Python/GObject/Print"
        self.filename = command[0]
        # print command arguments:
        # filename, file_data, mimetype, source_uuid, title, printer, no_copies, print_options_str = packet[1:9]
        self.command = command[1:]
        from xpra.util.parsing import parse_with_unit
        self.file_size_limit = parse_with_unit("file-size-limit", opts.file_size_limit, "B", min_value=0) or 0

        if self.filename == "-":
            # replace with filename proposed
            self.filename = command[2]
            # read file from stdin
            with open(sys.stdin.fileno(), mode="rb", closefd=False) as stdin_binary:
                self.file_data = stdin_binary.read()
            log("read %i bytes from stdin", len(self.file_data))
            if not self.validate_file_size(len(self.file_data)):
                return
        else:
            if not self.validate_file_size(os.path.getsize(self.filename)):
                return
            self.file_data = load_binary_file(self.filename)
            log("read %i bytes from %s", len(self.file_data), self.filename)
        if not self.validate_file_size(len(self.file_data)):
            return
        assert self.file_data, "no data found for '%s'" % self.filename

    def validate_file_size(self, size: int) -> bool:
        if size <= self.file_size_limit:
            return True
        self.warn_and_quit(ExitCode.FILE_TOO_BIG,
                           "the file is too large: %sB (the file size limit is %sB)" % (
                               std_unit(size), std_unit(self.file_size_limit)))
        return False

    def timeout(self, *_args) -> None:
        self.warn_and_quit(ExitCode.TIMEOUT, "timeout: server did not respond")

    def do_command(self, caps: typedict) -> None:
        printer = typedict(caps.dictget("printer", {}))
        if printer or not BACKWARDS_COMPATIBLE:
            info = printer.strget("info", "unknown")
            code = printer.intget("code", ExitCode.FAILURE)
            if code != 0:
                self.warn_and_quit(code, f"print request failed: {info!r}")
                return
            log.info("print request has been handled: %s", info)
            self.quit(ExitCode.OK)
            return
        assert BACKWARDS_COMPATIBLE
        # backwards compatible mode, send a separate print packet:
        printing = caps.boolget("printing")
        if not printing:
            self.warn_and_quit(ExitCode.UNSUPPORTED, "server does not support printing")
            return
        # we don't compress file data
        # (this should run locally most of the time anyway)
        from xpra.net.compression import Compressed  # pylint: disable=import-outside-toplevel
        blob = Compressed("print", self.file_data)
        self.send("print", self.filename, blob, *self.command)
        log("print: sending %s as %s for printing", self.filename, blob)
        GLib.idle_add(self.send, "disconnect", ConnectionMessage.DONE.value, "detaching")

    def make_hello(self) -> dict[str, Any]:
        capabilities = super().make_hello()
        capabilities.setdefault("wants", []).append("features")
        capabilities["request"] = "print"
        capabilities["print"] = ["print", self.filename, self.file_data] + list(self.command)
        return capabilities


class ExitXpraClient(HelloRequestClient):
    """ This client does one thing only:
        it asks the server to terminate (like stop),
        but without killing the Xvfb or clients.
    """

    def hello_request(self) -> dict[str, Any]:
        return {
            "request": "exit",
        }

    def do_command(self, caps: typedict) -> None:
        GLib.idle_add(self.send,
                      "exit-server",
                      os.environ.get("XPRA_EXIT_MESSAGE", ConnectionMessage.SERVER_EXIT.value)
                      )


class StopXpraClient(HelloRequestClient):
    """ stop a server """

    def hello_request(self) -> dict[str, Any]:
        return {
            "request": "stop",
        }

    def do_command(self, caps: typedict) -> None:
        if not self.server_client_shutdown:
            log.error("Error: cannot shutdown this server")
            log.error(" the feature is disabled on the server")
            self.quit(ExitCode.UNSUPPORTED)
            return
        # with newer (v5) servers, the "stop" request should have done it,
        # but let's try harder for older servers:
        GLib.timeout_add(1000, self.send_shutdown_server)
        # GLib.idle_add(self.send_shutdown_server)
        # not exiting the client here,
        # the server should send us the shutdown disconnection message anyway
        # and if not, we will then hit the timeout to tell us something went wrong


class DetachXpraClient(HelloRequestClient):
    """ run the `detach` subcommand """

    def hello_request(self) -> dict[str, Any]:
        return {
            "request": "detach",
        }

    def do_command(self, caps: typedict) -> None:
        GLib.idle_add(self.send, "disconnect", ConnectionMessage.DONE.value, "detaching")
        # not exiting the client here,
        # the server should disconnect us with the response


class WaitForDisconnectXpraClient(DetachXpraClient):
    """ we just want the connection to close """

    def _process_disconnect(self, _packet: Packet) -> None:
        self.quit(ExitCode.OK)


class RequestStartClient(HelloRequestClient):
    """ request the system proxy server to start a new session for us """
    # wait longer for this command to return:
    from xpra.scripts.main import WAIT_SERVER_TIMEOUT
    COMMAND_TIMEOUT = EXTRA_TIMEOUT + WAIT_SERVER_TIMEOUT

    def dots(self) -> bool:
        errwrite(".")
        return not self.connection_established

    def _process_connection_lost(self, packet: Packet) -> None:
        errwrite("\n")
        super()._process_connection_lost(packet)

    def hello_request(self) -> dict[str, Any]:
        if first_time("hello-request"):
            # this can be called again if we receive a challenge,
            # but only print this message once:
            errwrite("requesting new session, please wait")
        GLib.timeout_add(1 * 1000, self.dots)
        return {
            "start-new-session": self.start_new_session,
            # tells proxy servers we don't want to connect to the real / new instance:
            "connect": False,
        }

    def server_connection_established(self, caps: typedict) -> bool:
        # the server should respond with the display chosen
        log("server_connection_established() exit_code=%s", self.exit_code)
        display = caps.strget("display")
        if display:
            mode = caps.strget("mode")
            session_type = {
                "start": "seamless ",
                "start-desktop": "desktop ",
                "shadow": "shadow ",
            }.get(mode, "")
            try:
                errwrite("\n%ssession now available on display %s\n" % (session_type, display))
                if POSIX and not OSX and self.displayfd > 0 and display and display.startswith(":"):
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
