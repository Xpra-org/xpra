# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# the client subcommands, separated from main.py

import os
import sys
import signal
from subprocess import Popen, PIPE
from importlib.util import find_spec
from typing import Any
from collections.abc import Callable, Sequence

from xpra.common import noerr, may_show_progress, may_notify_client, set_progress_process
from xpra.util.str_fn import csv, bytestostr
from xpra.exit_codes import ExitCode, ExitValue, RETRY_EXIT_CODES, exit_str
from xpra.os_util import getuid, gi_import, WIN32, OSX, LINUX
from xpra.util.io import load_binary_file, warn, stderr_print
from xpra.util.system import set_proc_title
from xpra.scripts.parsing import validate_encryption
from xpra.config import InitException, InitInfo, InitExit
from xpra.config.fixup import fixup_options
from xpra.config.types import PROXY_START_OVERRIDABLE_OPTIONS
from xpra.config.defaults import get_defaults
from xpra.net.constants import SOCKET_TYPES, SocketState
from xpra.log import is_debug_enabled, Logger
from xpra.scripts.args import split_display_arg
from xpra.scripts.picker import pick_display, do_pick_display, connect_or_fail
from xpra.scripts.common import no_gi_gtk_modules

# pylint: disable=import-outside-toplevel


def werr(*msg) -> None:
    for x in msg:
        stderr_print(str(x))


def get_logger() -> Logger:
    return Logger("util")


def run_client(script_file, cmdline: list[str], opts, extra_args: list[str], mode: str) -> ExitValue:
    if mode != "attach":
        opts.reconnect = False
    if mode in ("attach", "detach") and len(extra_args) == 1 and extra_args[0] == "all":
        # run this command for each display:
        from xpra.platform.dotxpra import DotXpra
        dotxpra = DotXpra(opts.socket_dirs)
        displays = dotxpra.displays(check_uid=getuid(), matching_state=SocketState.LIVE)
        if not displays:
            sys.stdout.write("No xpra sessions found\n")
            return ExitCode.FILE_NOT_FOUND
        # we have to locate the 'all' command line argument,
        # so we can replace it with each display we find,
        # but some other command line arguments can take a value of 'all',
        # so we have to make sure that the one we find does not belong to the argument before
        index = None
        for i, arg in enumerate(cmdline):
            if i == 0 or arg != "all":
                continue
            prevarg = cmdline[i - 1]
            if prevarg[0] == "-" and (prevarg.find("=") < 0 or len(prevarg) == 2):
                # ie: [.., "--csc-modules", "all"] or [.., "-d", "all"]
                continue
            index = i
            break
        if not index:
            raise InitException("'all' command line argument could not be located")
        cmd = cmdline[:index] + cmdline[index + 1:]
        for display in displays:
            dcmd = cmd + [display] + ["--splash=no"]
            Popen(dcmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, close_fds=not WIN32)
        return ExitCode.OK
    app = get_client_app(cmdline, opts, extra_args, mode)
    r = do_run_client(app)
    if opts.reconnect is not False and r in RETRY_EXIT_CODES:
        warn("%s, reconnecting" % exit_str(r))
        return exec_reconnect(script_file, cmdline)
    return r


def exec_reconnect(script_file: str, cmdline: list[str]) -> ExitCode:
    if is_debug_enabled("client"):
        log = Logger("client")
        log.info(f"reconnecting using script file {script_file!r}")
        log.info(f" and {cmdline=}")
    try:
        if WIN32:
            return win32_reconnect(script_file, cmdline)
        else:
            abs_script_file = os.path.abspath(script_file)
            os.execv(abs_script_file, cmdline)
    except FileNotFoundError:
        warn(f"failed to re-connect using {script_file!r}")
        return ExitCode.FAILURE


def win32_reconnect(script_file: str, cmdline: list[str]) -> ExitCode:
    # the cx_Freeze wrapper changes the cwd to the directory containing the exe,
    # so we have to re-construct the actual path to the exe:
    # see issue #4026
    # we have to extract the exe name then get an abs path for it:
    # so that someone running xpra using:
    # `Xpra-x86_64_6.0-r34669M\xpra_cmd" attach ...`
    # will still end up with a valid absolute path
    # when the exe wrapper changes directory to `Xpra-x86_64_6.0-r34669M`.
    if not os.path.isabs(script_file):
        script_file = os.path.join(os.getcwd(), os.path.basename(script_file))
    if not os.path.exists(script_file):
        # perhaps the extension is missing?
        if not os.path.splitext(script_file)[1]:
            for ext in os.environ.get("PATHEXT", ".COM;.EXE").split(os.path.pathsep):
                tmp = script_file + ext
                if os.path.exists(tmp):
                    script_file = tmp
    cmdline[0] = script_file
    if is_debug_enabled("client"):
        log = Logger("client")
        log(f"Popen(args={cmdline}, executable={script_file}")
    Popen(args=cmdline, executable=script_file)
    # we can't keep re-spawning ourselves without freeing memory,
    # so exit the current process with "no error":
    return ExitCode.OK


def apply_ssl_retry(e: InitExit, display_desc: dict[str, Any]) -> bool:
    """
    If `e` is an SSL verification failure that the user chooses to override,
    update the ssl options in `display_desc` and return True so the caller connects again.
    Each retry must change the options or the certificate they use, so we can't keep retrying with the same ones.
    """
    from xpra.net.tls.socket import ssl_retry

    def ca_certs_data() -> bytes:
        return load_binary_file(display_desc.get("ssl-options", {}).get("ca-certs", ""))

    # the certificate we connected with may be replaced:
    data = ca_certs_data()
    mods = ssl_retry(e, display_desc)
    ssl_options = display_desc.setdefault("ssl-options", {})
    Logger("ssl")("ssl_retry(%s, %s)=%s", e, ssl_options, mods)
    if not mods or (all(ssl_options.get(k) == v for k, v in mods.items()) and ca_certs_data() == data):
        return False
    ssl_options.update(mods)
    return True


def connect_to_server(app, display_desc: dict[str, Any], opts) -> None:
    """
    Client-side entry point: dial the xpra server described by `display_desc` and hand the connection to `app`.

    Most backends run the connect step on a background thread so the GUI main loop stays responsive
    (and so Gdk doesn't lock up when `connect_to` spawns an ssh subprocess on win32).

    Synchronous failures (parse errors, refused connections, ssl errors, ...) raise `InitExit`/`InitException`
    and are routed to `app.quit` below.
    """
    log = Logger("network")
    backend = opts.backend or "gtk"
    log("connect_to_server(%s, %s, ..) backend=%s", app, display_desc, backend)
    # Subsystem run hooks need the target before the deferred connection starts.
    app.display = opts.display
    app.display_desc = display_desc

    def direct_call(fn: Callable, *args) -> None:
        fn(*args)
    call = direct_call

    if backend in ("qt", "pyglet", "tk", ):

        def setup_connection() -> None:
            do_setup_connection()

    else:
        # on win32, we must run the main loop
        # before we can call connect()
        # because connect() may run a subprocess,
        # and Gdk locks up the system if the main loop is not running by then!
        def setup_connection() -> None:
            log("setup_connection() starting setup-connection thread")
            from xpra.util.thread import start_thread
            start_thread(do_setup_connection, "setup-connection", True)

        GLib = gi_import("GLib")
        call = GLib.idle_add

    def do_setup_connection() -> None:
        try:
            log("do_setup_connection() display_desc=%s", display_desc)
            conn = connect_or_fail(display_desc)
            if not conn:
                raise RuntimeError("not connected")
            log("do_setup_connection() conn=%s", conn)
            # source the credentials from `display_desc` since `parse_display_name`
            # merges URL / opts / env / password-file into it during connect:
            if challenge := app.get_subsystem("challenge"):
                challenge.username = display_desc.get("username", "")
                challenge.password = display_desc.get("password", "")
            protocol = app.make_protocol(conn)
            protocol.start()
        except InitInfo as e:
            log("do_setup_connection() display_desc=%s", display_desc, exc_info=True)
            werr("failed to connect:", f" {e}")
            call(app.quit, ExitCode.OK)
        except InitExit as e:
            if apply_ssl_retry(e, display_desc):
                do_setup_connection()
                return
            werr("Warning: failed to connect:", f" {e}")
            call(app.quit, e.status)
        except InitException as e:
            log("do_setup_connection() display_desc=%s", display_desc, exc_info=True)
            werr("Warning: failed to connect:", f" {e}")
            call(app.quit, ExitCode.CONNECTION_FAILED)
        except Exception as e:
            log.error("do_setup_connection() display_desc=%s", display_desc, exc_info=True)
            werr("Error: failed to connect:", f" {e}")
            call(app.quit, ExitCode.CONNECTION_FAILED)

    call(setup_connection)


def basic_client_features():
    from xpra.client.base import features
    features.bandwidth = features.progress = features.file = features.printer = features.control = False
    features.info = features.server_info = features.server_events = features.debug = False
    return features


def get_client_app(cmdline: list[str], opts, extra_args: list[str], mode: str):
    app, extra_args, run_args = create_client_app(opts, extra_args, mode)
    if mode == "listen":
        return app
    return connect_client_app(app, cmdline, opts, extra_args, mode, run_args)


def create_client_app(opts, extra_args: list[str], mode: str):
    validate_encryption(opts)
    if not find_spec("xpra.client"):
        raise InitExit(ExitCode.COMPONENT_MISSING, "`xpra-client` is not installed")

    basic = basic_client_features

    request_mode = mode.replace("request-", "") if mode.startswith("request-") else ""
    run_args = []
    if mode in (
            "info", "id", "connect-test", "control", "version", "detach",
            "show-menu", "show-about", "show-session-info",
    ) and extra_args:
        opts.socket_dirs += opts.client_socket_dirs or []
    if mode in ("screenshot", "icon"):
        basic()
        if not extra_args:
            raise InitExit(ExitCode.ARGUMENT_MISMATCH, "invalid number of arguments for %s mode" % mode)
        if mode == "screenshot":
            from xpra.client.base.command import ScreenshotXpraClient as ImageClient
        else:
            from xpra.client.base.command import IconXpraClient as ImageClient
        filename = extra_args[0]
        extra_args = extra_args[1:]
        app = ImageClient(opts, filename)
    elif mode == "info":
        basic()
        from xpra.client.base.command import InfoXpraClient
        extra_args, subsystems = split_display_arg(extra_args)
        app = InfoXpraClient(opts, subsystems)
    elif mode == "id":
        basic()
        from xpra.client.base.command import IDXpraClient
        app = IDXpraClient(opts)
    elif mode in ("show-menu", "show-about", "show-session-info"):
        basic()
        from xpra.client.base.command import RequestXpraClient
        app = RequestXpraClient(request=mode, opts=opts)
    elif mode == "connect-test":
        basic()
        from xpra.client.base.command import ConnectTestXpraClient
        app = ConnectTestXpraClient(opts)
    elif mode == "record":
        from xpra.client.base.features import set_client_features
        # the recorder has nowhere to save a file, and cannot print or open a URL:
        # turning these off before the features are evaluated keeps the `file` and
        # `printer` subsystems out of the client, and out of its `hello` packet,
        # so that the server never sends it packets it has no handlers for
        opts.file_transfer = opts.printing = opts.open_files = opts.open_url = "no"
        set_client_features(opts)
        basic()
        from xpra.client.base.record import RecordClient
        app = RecordClient(opts)
        opts.encoding = handle_client_encoding_option(app, opts.encoding)
        app.init(opts)
        if opts.splash:
            from xpra import __version__
            from xpra.scripts.splash import make_progress_process
            set_progress_process(app, make_progress_process(opts.session_name or "Xpra Recorder v%s" % __version__))
    elif mode == "_monitor":
        # this client is only here to receive the server events:
        basic().server_events = True
        from xpra.client.base.command import MonitorXpraClient
        app = MonitorXpraClient(opts)
    elif mode == "shell":
        basic()
        from xpra.client.base.command import ShellXpraClient
        app = ShellXpraClient(opts)
    elif mode == "control":
        basic()
        from xpra.client.base.command import ControlXpraClient
        if len(extra_args) < 1:
            raise InitExit(ExitCode.ARGUMENT_MISMATCH, "not enough arguments for 'control' mode, try 'help'")
        extra_args, args = split_display_arg(extra_args)
        app = ControlXpraClient(opts, args)
    elif mode in ("run", "exec"):
        basic()
        from xpra.client.base.command import RunClient
        if len(extra_args) < 1:
            raise InitExit(ExitCode.ARGUMENT_MISMATCH, f"not enough arguments for '{mode}' mode, you must specify the command to execute")
        extra_args, run_args = split_display_arg(extra_args)
        app = RunClient(opts, run_args, mode)
    elif mode == "print":
        basic()
        from xpra.client.base.command import PrintClient
        if len(extra_args) <= 1:
            raise InitExit(ExitCode.ARGUMENT_MISMATCH, "not enough arguments for 'print' mode")
        extra_args, args = split_display_arg(extra_args)
        app = PrintClient(opts, args)
    elif mode == "qrcode":
        basic()
        from xpra.scripts.main import check_gtk
        check_gtk("qrcode")
        from xpra.gtk.dialogs.qrcode_client import QRCodeClient
        app = QRCodeClient(opts)
    elif mode == "version":
        basic()
        from xpra.client.base.command import VersionXpraClient
        app = VersionXpraClient(opts)
    elif mode == "detach":
        basic()
        from xpra.client.base.command import DetachXpraClient
        app = DetachXpraClient(opts)
    elif request_mode and opts.attach is not True:
        basic()
        from xpra.client.base.command import RequestStartClient
        sns = get_start_new_session_dict(opts, request_mode, extra_args)
        extra_args = [f"socket:{opts.system_proxy_socket}"]
        app = RequestStartClient(opts)
        app.hello_extra = {"connect": False}
        app.start_new_session = sns
    else:
        app = get_client_gui_app(opts, request_mode, extra_args, mode)
    return app, extra_args, run_args


def connect_client_app(app, cmdline: list[str], opts, extra_args: list[str], mode: str, run_args: list[str]):
    try:
        if mode != "listen":
            may_show_progress(app, 60, "connecting to server")
        if mode != "attach" and not extra_args:
            # try to guess the server intended:
            if server_socket := os.environ.get("XPRA_SERVER_SOCKET", ""):
                extra_args = [f"socket://{server_socket}"]
        display_desc = do_pick_display(opts, extra_args, cmdline)
        if len(extra_args) == 1 and opts.password:
            uri = extra_args[0]
            if uri in cmdline and opts.password in uri:
                # hide the password from the URI:
                i = cmdline.index(uri)
                # cmdline[i] = uri.replace(opts.password, "*"*len(opts.password))
                obsc_cmdline = list(cmdline)
                obsc_cmdline[i] = uri.replace(opts.password, "********")
                if not OSX:
                    set_proc_title(" ".join(obsc_cmdline))
        # use a custom proxy command for run mode:
        if mode in ("run", "exec") and display_desc.get("type", "") == "ssh":
            # when using the ssh transport,
            # don't try to connect to a server using the xpra protocol which may not exist,
            # the ssh command will do what is needed by calling `_proxy_run`:
            display_desc["proxy_command"] = ["_proxy_run"]
            if mode == "exec":
                display_desc["proxy_command"] = ["_proxy_exec"]
            if opts.backend and opts.backend.lower() != "auto":
                # forward the backend to the remote `_proxy_run` subcommand so that it can honour it:
                display_desc["display_as_args"].append(f"--backend={opts.backend}")
            display_desc["display_as_args"] += run_args
            app.display_desc = display_desc
        else:
            connect_to_server(app, display_desc, opts)
    except ValueError as e:
        einfo = str(e) or type(e)
        may_show_progress(app, 100, "error", einfo)
        app.cleanup()
        raise InitExit(ExitCode.FAILURE, f"invalid value: {einfo}")
    except Exception as e:
        einfo = str(e) or type(e)
        may_show_progress(app, 100, "error", einfo)
        app.cleanup()
        raise
    return app


def get_client_gui_app(opts, request_mode: str, extra_args: Sequence[str], mode: str):
    try:
        app = make_client(opts)
    except RuntimeError as e:
        log = get_logger()
        log("failed to create the client", exc_info=True)
        # exceptions at this point are still initialization exceptions
        msg = (e.args[0] if e.args else str(e)) or str(type(e))
        raise InitException(msg) from None
    may_show_progress(app, 30, "client configuration")
    try:
        opts.encoding = normalize_client_encoding_option(opts.encoding)
        if mode == "listen":
            listener = app.get_subsystem("listener")
            if listener is None:
                raise InitExit(ExitCode.COMPONENT_MISSING, "listen mode requires the client listener subsystem")
            listener.listen_mode = True
        app.init(opts)

        def handshake_complete(*_args) -> None:
            may_show_progress(app, 100, "connection established")
            log = get_logger()
            try:
                p = app._protocol
                if conn := p._conn:
                    log.info("Attached to %s server at %s", p.TYPE, conn.target)
                    log.info(" (press Control-C to detach)\n")
            except AttributeError:
                return

        if hasattr(app, "after_handshake"):
            app.after_handshake(handshake_complete)
        may_show_progress(app, 40, "initializing user interface")
        app.init_ui(opts)
        may_show_progress(app, 50, "loading user interface")
        app.load()
        # only now: validating an explicit encoding starts the decode thread, whose
        # `preload` hooks run against every other subsystem - and those want to be
        # initialized and loaded by then (`Notifications.preload_decode` looks at the
        # notifier `load` creates, for one):
        opts.encoding = handle_client_encoding_option(app, opts.encoding)
        if request_mode:
            sns = get_start_new_session_dict(opts, request_mode, extra_args)
            extra_args = [f"socket:{opts.system_proxy_socket}"]
            app.hello_extra = {
                "start-new-session": sns,
                "connect": True,
            }
            # we have consumed the start[-child] options
            app.start_child_new_commands = []
            app.start_new_commands = []

        if mode == "listen":
            if extra_args:
                raise InitException("cannot specify extra arguments with 'listen' mode")
            enable_listen_mode(app, opts)

    except Exception as e:
        may_show_progress(app, 100, "failure", e)
        from xpra.constants import NotificationID
        body = str(e)
        if body.startswith("failed to connect to"):
            lines = body.split("\n")
            summary = "Xpra client %s" % lines[0]
            body = "\n".join(lines[1:])
        else:
            summary = "Xpra client failed to connect"
        may_notify_client(app, NotificationID.FAILURE, summary, body, icon_name="disconnected")  # pylint: disable=not-callable
        app.cleanup()
        raise
    return app


def normalize_client_encoding_option(encoding: str) -> str:
    # `auto` is how the command line spells "no preference", which is what an unset
    # encoding means everywhere else. The subsystems only read `opts.encoding` once,
    # as they are initialized (see `Encodings.init`), so this has to happen before
    # they do - unlike the validation below, which needs the codecs loaded:
    return "" if encoding == "auto" else encoding


def handle_client_encoding_option(app, encoding: str) -> str:
    encoding = normalize_client_encoding_option(encoding)
    if not encoding:
        return ""
    from xpra.client.base import features
    if not features.encoding:
        return ""
    enc_subsystem = app.get_subsystem("encoding")
    if not enc_subsystem:
        return ""
    # `ensure_codecs_loaded` waits for the decode thread to load them, and the decode
    # subsystem is normally started by `app.run()` - which has not happened yet. Start it
    # here, or the wait below is a flat `XPRA_CODEC_LOAD_TIMEOUT` (30 seconds by default)
    # followed by loading the codecs on this thread, which is exactly what the decode
    # thread owns them to avoid (see `docs/Usage/Seccomp.md`):
    if decode := app.get_subsystem("decode"):
        decode.run()
    enc_subsystem.ensure_codecs_loaded()
    einfo = ""
    encodings = list(enc_subsystem.get_encodings()) + ["auto", "stream"]
    err = encoding not in encodings
    ehelp = encoding == "help"
    if err and not ehelp:
        einfo = f"invalid encoding: {encoding}\n"
    if err or ehelp:
        from xpra.codecs.loader import encodings_help
        raise InitInfo(einfo + "%s xpra client supports the following encodings:\n * %s" %
                       (app.client_toolkit(), "\n * ".join(encodings_help(encodings))))
    return encoding


def enable_listen_mode(app, opts):
    may_show_progress(app, 80, "listening for incoming connections")
    from xpra.net.socket_util import (
        peek_connection, accept_connection, SocketListener,
    )
    from xpra.log import Logger
    listener = app.get_subsystem("listener")

    def new_connection(listener: SocketListener) -> bool:
        from xpra.util.thread import start_thread
        netlog = Logger("network")
        netlog("new_connection(%s)", listener)
        conn = accept_connection(listener)
        # start a new thread so that we can sleep doing IO in `peek_connection`:
        start_thread(handle_new_connection, f"handle new connection: {conn}", daemon=True, args=(conn,))
        return True

    def handle_new_connection(conn) -> None:
        # see if this is a redirection:
        netlog = Logger("network")
        line1 = peek_connection(conn).split(b"\n", 1)[0]
        netlog.debug(f"handle_new_connection({conn}) line1={line1!r}")
        if line1:
            uri = bytestostr(line1)
            for socktype in SOCKET_TYPES:
                if uri.startswith(f"{socktype}://"):
                    conn.close()
                    run_socket_cleanups()
                    netlog.info(f"connecting to {uri}")
                    display_desc = pick_display(opts, [uri, ])
                    connect_to_server(app, display_desc, opts)
                    return
        app.idle_add(do_handle_connection, conn)

    def do_handle_connection(conn) -> None:
        protocol = app.make_protocol(conn)
        protocol.start()
        # stop listening for new connections:
        run_socket_cleanups()

    def run_socket_cleanups() -> None:
        listener.cleanup_sockets()

    listener.connection_handler = new_connection
    # listen mode is special,
    # don't fall through to connect_to_server!
    may_show_progress(app, 90, "ready")


def make_client(opts):
    backend = opts.backend or "gtk"
    if backend == "auto" and not _has_display() and sys.stdout.isatty() and sys.stdin.isatty():
        # no GUI display and we are attached to a terminal:
        # switch to the terminal client if it looks capable of rendering it
        from xpra.client.terminal.client import guess_kitty_capable_terminal
        if guess_kitty_capable_terminal():
            backend = "terminal"
    BACKENDS = ("qt", "gtk", "pyglet", "tk", "terminal", "win32", "auto") + ("native", ) * int(WIN32)
    if backend == "help":
        raise InitInfo("xpra clients support the following gui backends:\n * %s" % "\n * ".join(BACKENDS))
    if LINUX and backend in ("qt", "pyglet", "tk") and (opts.landlock or "no") != "no":
        raise InitExit(ExitCode.UNSUPPORTED, f"the {backend} client does not support Landlock; use --landlock=no")
    # before importing the toolkits, so that their DLLs are loaded with the restricted search order:
    from xpra.platform.security import harden_process
    try:
        harden_process()
    except OSError as e:
        warn(f"Warning: failed to harden the client process: {e}")
    if backend == "qt":
        no_gi_gtk_modules()
        try:
            from xpra.client.qt6.client import make_client as make_qt6_client
            return make_qt6_client()
        except ImportError as e:
            get_logger().debug("importing qt6 client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the qt6 client component is missing: {e}") from None
    if backend == "pyglet":
        no_gi_gtk_modules()
        try:
            from xpra.client.pyglet.client import make_client as make_pyglet_client
            return make_pyglet_client()
        except ImportError as e:
            get_logger().debug("importing pyglet client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the pyglet client component is missing: {e}") from None
    if backend == "tk":
        no_gi_gtk_modules()
        try:
            from xpra.client.tk.client import make_client as make_tk_client
            return make_tk_client()
        except ImportError as e:
            get_logger().debug("importing tk client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the tk client component is missing: {e}") from None
    if backend == "terminal":
        no_gi_gtk_modules()
        # the splash screen is a Gtk process which would fight for the terminal:
        opts.splash = False
        # there is no OpenGL rendering into a terminal
        # (`get_gl_client_window_module()` never returns one):
        opts.opengl = "no"
        # there is nowhere to put a system tray icon in a terminal
        # (`get_system_tray_classes()` returns nothing), so the tray forwarding
        # must not be advertised to the server - it would send us tray windows
        # we have no way of creating:
        opts.system_tray = False
        # the terminal client composes its subsystems from the client features,
        # which is why the options above are turned off first:
        from xpra.client.base.features import set_client_features
        set_client_features(opts)
        try:
            from xpra.client.terminal.client import make_client as make_terminal_client
            return make_terminal_client(opts)
        except ImportError as e:
            get_logger().debug("importing terminal client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the terminal client component is missing: {e}") from None
    if backend == "win32":
        no_gi_gtk_modules()
        # probe before the client exists: `init_opengl` runs later, from `client.init(opts)`
        if opts.opengl in ("probe", "nowarn"):
            from xpra.scripts.glprobe import probe_opengl
            probe_opengl(opts)
        try:
            from xpra.client.win32.client import make_client as make_win32_client
            return make_win32_client(opts)
        except ImportError as e:
            get_logger().debug("importing win32 client", backtrace=True)
            raise InitExit(ExitCode.COMPONENT_MISSING, f"the tk client component is missing: {e}") from None
    if backend not in ("gtk", "auto"):
        raise ValueError(f"invalid gui backend {backend!r}, must be one of: "+csv(BACKENDS))

    progress_process = None
    # noinspection simplify-boolean-check
    if opts.splash is not False:
        from xpra import __version__
        title = opts.session_name or "Xpra Client v%s" % __version__
        from xpra.scripts.splash import make_progress_process
        progress_process = make_progress_process(title)

    try:
        from xpra.scripts.main import check_gtk_client
        check_gtk_client()

        from xpra.platform.gui import init as gui_init
        gui_init()

        from xpra.client.base.features import set_client_features
        set_client_features(opts)

        from xpra.client.gtk3.client import XpraClient
        app = XpraClient()
        set_progress_process(app, progress_process)

        if opts.opengl in ("probe", "nowarn"):
            may_show_progress(app, 20, "validating OpenGL configuration")
            from xpra.scripts.glprobe import probe_opengl
            r, message = probe_opengl(opts)
            may_show_progress(app, 20, "validating OpenGL", r)
            if message:
                may_show_progress(app, 21, f" {message}")

    except Exception:
        if progress_process:
            noerr(progress_process.terminate)
        raise
    return app


def do_run_client(app) -> ExitValue:
    try:
        return app.run()
    except KeyboardInterrupt:
        return -signal.SIGINT
    finally:
        app.cleanup()


def get_start_new_session_dict(opts, mode: str, extra_args) -> dict[str, Any]:
    sns = {
        "mode": mode,  # ie: "start-desktop"
    }
    if len(extra_args) == 1:
        sns["display"] = extra_args[0]
    from xpra.config.types import dict_to_config
    defaults = dict_to_config(get_defaults())
    fixup_options(defaults)
    for x in PROXY_START_OVERRIDABLE_OPTIONS:
        fn = x.replace("-", "_")
        v = getattr(opts, fn)
        dv = getattr(defaults, fn, None)
        if v and v != dv:
            sns[x] = v
    # make sure the server will start in the same path we were called from:
    # (despite being started by a root owned process from a different directory)
    if not opts.chdir:
        sns["chdir"] = os.getcwd()
    return sns


def _has_display() -> bool:
    if WIN32 or OSX:
        return True
    import os
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_top(options, args: list[str], cmdline: list[str]) -> ExitValue:
    if not args and _has_display():
        from xpra.gtk.dialogs.top import main as run_top_gui
        run_top_gui(options)
        return 0
    from xpra.client.base.top import TopClient, TopSessionClient
    if args:
        # try to show a specific session
        try:
            display_desc = pick_display(options, args, cmdline)
        except Exception:
            pass
        else:
            # show the display we picked automatically:
            top_session = TopSessionClient(options)
            try:
                connect_to_server(top_session, display_desc, options)
                return top_session.run()
            except Exception:
                pass
    return TopClient(options).run()


def run_encode(options, args: list[str], cmdline: list[str]) -> ExitValue:
    from xpra.client.base.features import set_client_features
    set_client_features(options)
    from xpra.client.base.encode import EncodeClient
    display_desc = pick_display(options, args[:1], cmdline)
    app = EncodeClient(options, args[1:])
    app.init(options)
    connect_to_server(app, display_desc, options)
    return app.run()


def run_session_info(options, args: list[str], cmdline: list[str]) -> ExitValue:
    display_desc = pick_display(options, args, cmdline)
    from xpra.gtk.dialogs.session_info import SessionInfoClient
    app = SessionInfoClient(options)
    connect_to_server(app, display_desc, options)
    return app.run()
