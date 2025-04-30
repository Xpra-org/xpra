# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable-msg=E1101

import os.path
from time import monotonic

from xpra.util.parsing import parse_scaling_value, from0to100
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.common import ConnectionMessage, noop
from xpra.util.io import load_binary_file
from xpra.net.common import PacketType
from xpra.util.stats import std_unit
from xpra.scripts.config import str_to_bool, FALSE_OPTIONS, TRUE_OPTIONS
from xpra.net.control.common import ArgsControlCommand, ControlError
from xpra.server.mixins.stub_server_mixin import StubServerMixin
from xpra.log import Logger

log = Logger("command")

TOGGLE_FEATURES = (
    "bell", "randr", "cursors", "notifications", "clipboard",
    "start-new-commands", "client-shutdown", "webcam",
)


class ServerBaseControlCommands(StubServerMixin):
    """
    Control commands for ServerBase
    """
    PREFIX = "control"

    def setup(self) -> None:
        self.add_control_commands()

    def add_control_commands(self) -> None:
        def parse_boolean_value(v):
            if str(v).lower() in TRUE_OPTIONS:
                return True
            if str(v).lower() in FALSE_OPTIONS:
                return False
            raise ControlError(f"a boolean is required, not {v!r}")

        def parse_4intlist(v) -> list:
            if not v:
                return []
            intlist = []
            # ie: v = " (0,10,100,20), (200,300,20,20)"
            while v:
                v = v.strip().strip(",").strip()  # ie: "(0,10,100,20)"
                lp = v.find("(")
                assert lp == 0, "invalid leading characters: %s" % v[:lp]
                rp = v.find(")")
                assert (lp + 1) < rp
                item = v[lp + 1:rp].strip()  # "0,10,100,20"
                items = [int(x) for x in item]  # 0,10,100,20
                assert len(items) == 4, f"expected 4 numbers but got {len(items)}"
                intlist.append(items)
            return intlist

        for cmd in (
                ArgsControlCommand("focus", "give focus to the window id", validation=[int]),
                ArgsControlCommand("map", "maps the window id", validation=[int]),
                ArgsControlCommand("unmap", "unmaps the window id", validation=[int]),
                # window source:
                ArgsControlCommand("suspend", "suspend screen updates", max_args=0),
                ArgsControlCommand("resume", "resume screen updates", max_args=0),
                ArgsControlCommand("ungrab", "cancels any grabs", max_args=0),
                # server globals:
                ArgsControlCommand("readonly", "set readonly state for client(s)", min_args=1, max_args=1,
                                   validation=[parse_boolean_value]),
                ArgsControlCommand("idle-timeout", "set the idle timeout", validation=[int]),
                ArgsControlCommand("server-idle-timeout", "set the server idle timeout", validation=[int]),
                ArgsControlCommand("start-env", "modify the environment used to start new commands", min_args=2),
                ArgsControlCommand("start", "executes the command arguments in the server context", min_args=1),
                ArgsControlCommand("start-child",
                                   "executes the command arguments in the server context, as a 'child' (honouring exit-with-children)",
                                   min_args=1),
                ArgsControlCommand("toggle-feature",
                                   "toggle a server feature on or off, one of: %s" % csv(TOGGLE_FEATURES), min_args=1,
                                   max_args=2, validation=[str, parse_boolean_value]),
                # network and transfers:
                ArgsControlCommand("print", "sends the file to the client(s) for printing", min_args=1),
                ArgsControlCommand("open-url", "open the URL on the client(s)", min_args=1, max_args=2),
                ArgsControlCommand("send-file", "sends the file to the client(s)", min_args=1, max_args=4),
                ArgsControlCommand("send-notification", "sends a notification to the client(s)", min_args=4, max_args=5,
                                   validation=[int]),
                ArgsControlCommand("close-notification",
                                   "send the request to close an existing notification to the client(s)", min_args=1,
                                   max_args=2, validation=[int]),
                ArgsControlCommand("compression", "sets the packet compressor", min_args=1, max_args=1),
                ArgsControlCommand("encoder", "sets the packet encoder", min_args=1, max_args=1),
                ArgsControlCommand("clipboard-direction", "restrict clipboard transfers", min_args=1, max_args=1),
                ArgsControlCommand("clipboard-limits", "restrict clipboard transfers size", min_args=2, max_args=2,
                                   validation=[int, int]),
                ArgsControlCommand("set-lock", "modify the lock attribute", min_args=1, max_args=1),
                ArgsControlCommand("set-sharing", "modify the sharing attribute", min_args=1, max_args=1),
                ArgsControlCommand("set-ui-driver", "set the client connection driving the session", min_args=1,
                                   max_args=1),
                # session and clients:
                ArgsControlCommand("client", "forwards a control command to the client(s)", min_args=1),
                ArgsControlCommand("client-property", "set a client property", min_args=4, max_args=5,
                                   validation=[int]),
                ArgsControlCommand("name", "set the session name", min_args=1, max_args=1),
                ArgsControlCommand("key", "press or unpress a key", min_args=1, max_args=2),
                ArgsControlCommand("audio-output", "control audio forwarding", min_args=1, max_args=2),
                # windows:
                ArgsControlCommand("workspace", "move a window to a different workspace", min_args=2, max_args=2,
                                   validation=[int, int]),
                ArgsControlCommand("close", "close a window", min_args=1, max_args=1, validation=[int]),
                ArgsControlCommand("delete", "delete a window", min_args=1, max_args=1, validation=[int]),
                ArgsControlCommand("move", "move a window", min_args=3, max_args=3, validation=[int, int, int]),
                ArgsControlCommand("resize", "resize a window", min_args=3, max_args=3, validation=[int, int, int]),
                ArgsControlCommand("moveresize", "move and resize a window", min_args=5, max_args=5,
                                   validation=[int, int, int, int, int]),
                ArgsControlCommand("scaling-control", "set the scaling-control aggressiveness (from 0 to 100)",
                                   min_args=1, validation=[from0to100]),
                ArgsControlCommand("scaling", "set a specific scaling value", min_args=1,
                                   validation=[parse_scaling_value]),
                ArgsControlCommand("auto-refresh", "set a specific auto-refresh value", min_args=1, validation=[float]),
                ArgsControlCommand("refresh", "refresh some or all windows", min_args=0),
                ArgsControlCommand("encoding", "picture encoding", min_args=2),
                ArgsControlCommand("request-update", "request a screen update using a specific encoding", min_args=3),
                ArgsControlCommand("video-region-enabled", "enable video region", min_args=2, max_args=2,
                                   validation=[int, parse_boolean_value]),
                ArgsControlCommand("video-region-detection", "enable video detection", min_args=2, max_args=2,
                                   validation=[int, parse_boolean_value]),
                ArgsControlCommand("video-region-exclusion-zones",
                                   "set window regions to exclude from video regions: 'WID,(x,y,w,h),(x,y,w,h),..', ie: '1 (0,10,100,20),(200,300,20,20)'",
                                   min_args=2, max_args=2, validation=[int, parse_4intlist]),
                ArgsControlCommand("video-region", "set the video region", min_args=5, max_args=5,
                                   validation=[int, int, int, int, int]),
                ArgsControlCommand("reset-video-region", "reset video region heuristics", min_args=1, max_args=1,
                                   validation=[int]),
                ArgsControlCommand("lock-batch-delay", "set a specific batch delay for a window", min_args=2,
                                   max_args=2, validation=[int, int]),
                ArgsControlCommand("unlock-batch-delay",
                                   "let the heuristics calculate the batch delay again for a window (following a 'lock-batch-delay')",
                                   min_args=1, max_args=1, validation=[int]),
                ArgsControlCommand("remove-window-filters", "remove all window filters", min_args=0, max_args=0),
                ArgsControlCommand("add-window-filter", "add a window filter", min_args=4, max_args=5),
        ):
            cmd.do_run = getattr(self, "control_command_%s" % cmd.name.replace("-", "_"), noop)
            if cmd.do_run != noop:
                self.add_control_command(cmd.name, cmd)
        # encoding bits:
        for name in (
                "quality", "min-quality", "max-quality",
                "speed", "min-speed", "max-speed",
        ):
            fn = getattr(self, "control_command_%s" % name.replace("-", "_"), noop)
            if fn != noop:
                self.add_control_command(name, ArgsControlCommand(name, "set encoding %s (from 0 to 100)" % name, run=fn,
                                                                  min_args=1, validation=[from0to100]))

    #########################################
    # Control Commands
    #########################################
    def control_command_focus(self, wid: int) -> str:
        if self.readonly:
            return "focus request denied by readonly mode"
        if not isinstance(wid, int):
            raise ValueError(f"argument should have been an int, but found {type(wid)}")
        self._focus(None, wid, None)
        return f"gave focus to window {wid}"

    def control_command_map(self, wid: int) -> str:
        if self.readonly:
            return "map request denied by readonly mode"
        if not isinstance(wid, int):
            raise ValueError(f"argument should have been an int, but found {type(wid)}")
        window = self._id_to_window.get(wid)
        assert window, f"window {wid} not found"
        if window.is_tray():
            return f"cannot map tray window {wid}"
        if window.is_OR():
            return f"cannot map override redirect window {wid}"
        window.show()
        # window.set_owner(dm)
        # iconic = window.get_property("iconic")
        # if iconic:
        #    window.set_property("iconic", False)
        # w, h = window.get_geometry()[2:4]
        # self.refresh_window_area(window, 0, 0, w, h)
        self.repaint_root_overlay()
        return "mapped window %s" % wid

    def control_command_unmap(self, wid: int) -> str:
        if self.readonly:
            return "unmap request denied by readonly mode"
        if not isinstance(wid, int):
            raise ValueError(f"argument should have been an int, but found {type(wid)}")
        window = self._id_to_window.get(wid)
        assert window, f"window {wid} not found"
        if window.is_tray():
            return f"cannot unmap tray window {wid}"
        if window.is_OR():
            return f"cannot unmap override redirect window {wid}"
        window.hide()
        self.repaint_root_overlay()
        return f"unmapped window {wid}"

    def control_command_suspend(self) -> str:
        for csource in tuple(self._server_sources.values()):
            csource.suspend(True, self._id_to_window)
        count = len(self._server_sources)
        return f"suspended {count} clients"

    def control_command_resume(self) -> str:
        for csource in tuple(self._server_sources.values()):
            csource.resume(True, self._id_to_window)
        count = len(self._server_sources)
        return f"resumed {count} clients"

    def control_command_ungrab(self) -> str:
        for csource in tuple(self._server_sources.values()):
            csource.pointer_ungrab(-1)
        count = len(self._server_sources)
        return f"ungrabbed {count} clients"

    def control_command_readonly(self, onoff) -> str:
        log("control_command_readonly(%s)", onoff)
        self.readonly = onoff
        msg = f"server readonly: {onoff}"
        log.info(msg)
        return msg

    def control_command_idle_timeout(self, t: int) -> str:
        self.idle_timeout = t
        for csource in tuple(self._server_sources.values()):
            csource.idle_timeout = t
            csource.schedule_idle_timeout()
        return f"idle-timeout set to {t}"

    def control_command_server_idle_timeout(self, t: int) -> str:
        self.server_idle_timeout = t
        reschedule = len(self._server_sources) == 0
        self.reset_server_timeout(reschedule)
        return f"server-idle-timeout set to {t}"

    def control_command_start_env(self, action: str = "set", var_name: str = "", value=None) -> str:
        assert var_name, "the environment variable name must be specified"
        if action == "unset":
            assert value is None, f"invalid number of arguments for {action}"
            if self.start_env.pop(var_name, None) is None:
                return f"{var_name!r} is not set"
            return f"{var_name} unset"
        if action == "set":
            assert value, "the value must be specified"
            self.start_env[var_name] = value
            return f"{var_name}={value}"
        return f"invalid start-env subcommand {action!r}"

    def control_command_start(self, *args) -> str:
        return self.do_control_command_start(True, *args)

    def control_command_start_child(self, *args) -> str:
        return self.do_control_command_start(False, *args)

    def do_control_command_start(self, ignore, *args) -> str:
        if not self.start_new_commands:
            raise ControlError("this feature is currently disabled")
        proc = self.start_command(" ".join(args), args, ignore)
        if not proc:
            raise ControlError("failed to start new child command " + str(args))
        return "new %scommand started with pid=%s" % (["child ", ""][ignore], proc.pid)

    def control_command_toggle_feature(self, feature, state=None) -> str:
        log("control_command_toggle_feature(%s, %s)", feature, state)
        if feature not in TOGGLE_FEATURES:
            msg = f"invalid feature {feature!r}"
            log.warn(msg)
            return msg
        fn = feature.replace("-", "_")
        if not hasattr(self, feature):
            msg = f"attribute {feature!r} not found - bug?"
            log.warn(msg)
            return msg
        cur = getattr(self, fn, None)
        if state is None:
            # if the new state is not specified, just negate the value
            state = not cur
        setattr(self, fn, state)
        self.setting_changed(feature, state)
        return f"{feature} set to {state}"

    def _control_get_sources(self, client_uuids_str, _attr=None):
        # find the client uuid specified as a string:
        if client_uuids_str == "UI":
            sources = [ss for ss in self._server_sources.values() if ss.ui_client]
        elif client_uuids_str == "*":
            sources = self._server_sources.values()
        else:
            client_uuids = client_uuids_str.split(",")
            sources = [ss for ss in self._server_sources.values() if ss.uuid in client_uuids]
            uuids = tuple(ss.uuid for ss in sources)
            notfound = any(x for x in client_uuids if x not in uuids)
            if notfound:
                log.warn(f"Warning: client connection not found for uuid(s): {notfound}")
        return sources

    def control_command_send_notification(self, nid: int, title: str, message: str, client_uuids) -> str:
        if not self.notifications:
            msg = "notifications are disabled"
            log(msg)
            return msg
        sources = self._control_get_sources(client_uuids)
        log("control_command_send_notification(%i, %s, %s, %s) will send to sources %s (matching %s)",
            nid, title, message, client_uuids, sources, client_uuids)
        count = 0
        for source in sources:
            if source.notify(0, nid, "control channel", 0, "", title, message, [], {}, 10, ""):
                count += 1
        msg = f"notification id {nid}: message sent to {count} clients"
        log(msg)
        return msg

    def control_command_close_notification(self, nid: int, client_uuids) -> str:
        if not self.notifications:
            msg = "notifications are disabled"
            log(msg)
            return msg
        sources = self._control_get_sources(client_uuids)
        log("control_command_close_notification(%s, %s) will send to %s", nid, client_uuids, sources)
        for source in sources:
            source.notify_close(nid)
        msg = f"notification id {nid}: close request sent to {len(sources)} clients"
        log(msg)
        return msg

    def control_command_open_url(self, url: str, client_uuids="*") -> str:
        # find the clients:
        sources = self._control_get_sources(client_uuids)
        if not sources:
            raise ControlError(f"no clients found matching: {client_uuids!r}")
        clients = 0
        for ss in sources:
            if hasattr(ss, "send_open_url") and ss.send_open_url(url):
                clients += 1
        return f"url sent to {clients} clients"

    def control_command_send_file(self, filename: str, openit="open", client_uuids="*", maxbitrate=0) -> str:
        # we always get the values as strings from the command interface,
        # but those may actually be utf8 encoded binary strings,
        # so we may have to do an ugly roundtrip:
        openit = str(openit).lower() in ("open", "true", "1")
        return self.do_control_file_command("send file", client_uuids, filename, "file_transfer", (False, openit))

    def control_command_print(self, filename: str, printer="", client_uuids="*",
                              maxbitrate=0, title="", *options_strs) -> str:
        # FIXME: printer and bitrate are ignored
        # parse options into a dict:
        options = {}
        for arg in options_strs:
            argp = arg.split("=", 1)
            if len(argp) == 2 and len(argp[0]) > 0:
                options[argp[0]] = argp[1]
        return self.do_control_file_command("print", client_uuids, filename, "printing", (True, True, options))

    def do_control_file_command(self, command_type, client_uuids, filename, source_flag_name, send_file_args) -> str:
        # find the clients:
        sources = self._control_get_sources(client_uuids)
        if not sources:
            raise ControlError(f"no clients found matching: {client_uuids!r}")

        filelog = Logger("command", "file")

        def checksize(file_size):
            if file_size > self.file_transfer.file_size_limit:
                raise ControlError("file '%s' is too large: %sB (limit is %sB)" % (
                    filename, std_unit(file_size), std_unit(self.file_transfer.file_size_limit)))

        # find the file and load it:
        actual_filename = os.path.abspath(os.path.expanduser(filename))
        try:
            stat = os.stat(actual_filename)
            filelog("os.stat(%s)=%s", actual_filename, stat)
        except os.error:
            filelog("os.stat(%s)", actual_filename, exc_info=True)
        else:
            checksize(stat.st_size)
        if not os.path.exists(actual_filename):
            raise ControlError(f"file {filename!r} does not exist")
        data = load_binary_file(actual_filename)
        if not data:
            raise ControlError(f"no data loaded from {actual_filename!r}")
        # verify size:
        file_size = len(data)
        checksize(file_size)
        # send it to each client:
        for ss in sources:
            # ie: ServerSource.file_transfer (found in FileTransferAttributes)
            #     and ServerSource.remote_file_transfer (found in FileTransferHandler)
            server_support = getattr(ss, source_flag_name, False)
            client_support = getattr(ss, f"remote_{source_flag_name}", False)
            if not (server_support and client_support):
                # skip the warning if the client is not interactive
                # (for now just check for 'top' client):
                if not hasattr(ss, source_flag_name) or ss.client_type == "top":
                    log_fn = filelog.debug
                else:
                    log_fn = filelog.warn
                log_fn(f"Warning: cannot {command_type} {filename!r} to {ss.client_type} client")
                log_fn(f" feature flag {source_flag_name!r}")
                if not server_support:
                    log_fn(" this feature is not supported by the server connection")
                if not client_support:
                    log_fn(f" client {ss.uuid} does not support this feature")
            elif file_size > ss.file_size_limit:
                filelog.warn(f"Warning: cannot {command_type} {filename!r}")
                filelog.warn(" client %s file size limit is %sB (file is %sB)",
                             ss, std_unit(ss.file_size_limit), std_unit(file_size))
            else:
                filelog(f"sending {filename} to {ss}")
                ss.send_file(filename, "", data, file_size, *send_file_args)
        return f"{command_type} of {filename!r} to {client_uuids} initiated"

    def control_command_remove_window_filters(self) -> str:
        # modify the existing list object,
        # which is referenced by all the sources
        count = len(self.window_filters)
        self.window_filters[:] = []
        return f"removed {count} window-filters"

    def control_command_add_window_filter(self, object_name: str, property_name: str, operator: str, value,
                                          client_uuids="") -> str:
        from xpra.server.window import filters  # pylint: disable=import-outside-toplevel
        window_filter = filters.get_window_filter(object_name, property_name, operator, value)
        # log("%s%s=%s", filters.get_window_filter, (object_name, property_name, operator, value), window_filter)
        if client_uuids == "*":
            # applies to all sources:
            self.window_filters.append(("*", window_filter))
        else:
            for client_uuid in client_uuids.split(","):
                self.window_filters.append((client_uuid, window_filter))
        return f"added window-filter: {window_filter} for client uuids={client_uuids}"

    def control_command_compression(self, compress: str) -> str:
        c = compress.lower()
        from xpra.net import compression  # pylint: disable=import-outside-toplevel
        opts = compression.get_enabled_compressors()  # ie: [lz4, zlib]
        if c not in opts:
            raise ControlError("compressor argument must be one of: " + csv(opts))
        for cproto in tuple(self._server_sources.keys()):
            cproto.enable_compressor(c)
        self.all_send_client_command(f"enable_{c}")
        return f"compressors set to {compression}"

    def control_command_encoder(self, encoder: str) -> str:
        e = encoder.lower()
        from xpra.net import packet_encoding  # pylint: disable=import-outside-toplevel
        opts = packet_encoding.get_enabled_encoders()  # ie: [rencodeplus, ]
        if e not in opts:
            raise ControlError("encoder argument must be one of: " + csv(opts))
        for cproto in tuple(self._server_sources.keys()):
            cproto.enable_encoder(e)
        self.all_send_client_command(f"enable_{e}")
        return f"encoders set to {encoder}"

    def all_send_client_command(self, *client_command) -> None:
        """ forwards the command to all clients """
        for source in tuple(self._server_sources.values()):
            # forwards to *the* client, if there is *one*
            if client_command[0] not in source.client_control_commands:
                log.info(f"client command {client_command!r} not forwarded to client {source} (not supported)")
            else:
                source.send_client_command(*client_command)

    def control_command_client(self, *args) -> str:
        self.all_send_client_command(*args)
        return f"client control command {args} forwarded to clients"

    def control_command_client_property(self, wid: int, uuid, prop: str, value, conv=None) -> str:
        wid = int(wid)
        conv_fn = {
            "int": int,
            "float": float,
            "": str,
        }.get(conv)
        assert conv_fn
        typeinfo = "%s " % (conv or "string")
        value = conv_fn(value)
        self.client_properties.setdefault(wid, {}).setdefault(uuid, {})[prop] = value
        return f"property {prop!r} set to {typeinfo} value {value!r} for window {wid}, client {uuid}"

    def control_command_name(self, name: str) -> str:
        self.session_name = name
        log.info(f"changed session name: {self.session_name!r}")
        # self.all_send_client_command("name", name)    not supported by any clients, don't bother!
        self.setting_changed("session_name", name)
        self.mdns_update()
        return f"session name set to {name}"

    def _ws_from_args(self, *args):
        # converts the args to valid window ids,
        # then returns all the window sources for those wids
        if len(args) == 0 or len(args) == 1 and args[0] == "*":
            # default to all if unspecified:
            wids = tuple(self._id_to_window.keys())
        else:
            wids = []
            for x in args:
                try:
                    wid = int(x)
                except ValueError:
                    raise ControlError(f"invalid window id: {x!r}") from None
                if wid in self._id_to_window:
                    wids.append(wid)
                else:
                    log(f"window id {wid} does not exist")
        wss = []
        for csource in tuple(self._server_sources.values()):
            for wid in wids:
                ws = csource.window_sources.get(wid)
                window = self._id_to_window.get(wid)
                if window and ws:
                    wss.append(ws)
        return wss

    def _set_encoding_property(self, name: str, value, *wids) -> str:
        for ws in self._ws_from_args(*wids):
            fn = getattr(ws, "set_" + name.replace("-", "_"))  # ie: "set_quality"
            fn(value)
        # now also update the defaults:
        for csource in tuple(self._server_sources.values()):
            csource.default_encoding_options[name] = value
        return f"{name} set to {value}"

    def control_command_quality(self, quality: int, *wids) -> str:
        return self._set_encoding_property("quality", quality, *wids)

    def control_command_min_quality(self, min_quality: int, *wids) -> str:
        return self._set_encoding_property("min-quality", min_quality, *wids)

    def control_command_max_quality(self, max_quality: int, *wids) -> str:
        return self._set_encoding_property("max-quality", max_quality, *wids)

    def control_command_speed(self, speed: int, *wids) -> str:
        return self._set_encoding_property("speed", speed, *wids)

    def control_command_min_speed(self, min_speed: int, *wids) -> str:
        return self._set_encoding_property("min-speed", min_speed, *wids)

    def control_command_max_speed(self, max_speed: int, *wids) -> str:
        return self._set_encoding_property("max-speed", max_speed, *wids)

    def control_command_auto_refresh(self, auto_refresh, *wids) -> str:
        delay = int(float(auto_refresh) * 1000.0)  # ie: 0.5 -> 500 (milliseconds)
        for ws in self._ws_from_args(*wids):
            ws.set_auto_refresh_delay(auto_refresh)
        return f"auto-refresh delay set to {delay}ms for windows {wids}"

    def control_command_refresh(self, *wids) -> str:
        for ws in self._ws_from_args(*wids):
            ws.full_quality_refresh({})
        return f"refreshed windows {wids}"

    def control_command_scaling_control(self, scaling_control, *wids) -> str:
        for ws in tuple(self._ws_from_args(*wids)):
            ws.set_scaling_control(scaling_control)
            ws.refresh()
        return f"scaling-control set to {scaling_control} on windows {wids}"

    def control_command_scaling(self, scaling, *wids) -> str:
        for ws in tuple(self._ws_from_args(*wids)):
            ws.set_scaling(scaling)
            ws.refresh()
        return f"scaling set to {scaling} on windows {wids}"

    def control_command_encoding(self, encoding: str, *args) -> str:
        if encoding in ("add", "remove"):
            cmd = encoding
            assert len(args) > 0
            encoding = args[0]
            wids = args[1:]
            for ws in tuple(self._ws_from_args(*wids)):
                encodings = list(ws.encodings)
                core_encodings = list(ws.core_encodings)
                for enc_list in (encodings, core_encodings):
                    if cmd == "add" and encoding not in enc_list:
                        log(f"adding {encoding} to {enc_list} for {ws}")
                        enc_list.append(encoding)
                    elif cmd == "remove" and encoding in enc_list:
                        log(f"removing {encoding} to {enc_list} for {ws}")
                        enc_list.remove(encoding)
                    else:
                        continue
                ws.encodings = tuple(encodings)
                ws.core_encodings = tuple(core_encodings)
                ws.do_set_client_properties(typedict())
                ws.refresh()
            return ["removed", "added"][cmd == "add"] + " " + encoding

        strict = None  # means no change
        if encoding in ("strict", "nostrict"):
            strict = encoding == "strict"
            encoding = args[0]
            wids = args[1:]
        elif len(args) > 0 and args[0] in ("strict", "nostrict"):
            # remove "strict" marker
            strict = args[0] == "strict"
            wids = args[1:]
        else:
            wids = args
        for ws in tuple(self._ws_from_args(*wids)):
            ws.set_new_encoding(encoding, strict)
            ws.refresh()
        return f"set encoding to {encoding}%s for windows {wids}" % ["", " (strict)"][int(strict or 0)]

    def control_command_request_update(self, encoding: str, geom, *args) -> str:
        wids = args
        now = monotonic()
        options = {
            "auto_refresh": True,
            "av-delay": 0,
        }
        log("request-update using %r, geometry=%s, windows(%s)=%s", encoding, geom, wids, self._ws_from_args(*wids))
        for ws in tuple(self._ws_from_args(*wids)):
            if geom == "all":
                x = y = 0
                w, h = ws.window_dimensions
            else:
                x, y, w, h = (int(x) for x in geom.split(","))
            ws.process_damage_region(now, x, y, w, h, encoding, options)
        return "damage requested"

    def control_command_clipboard_direction(self, direction: str, *_args) -> str:
        ch = self._clipboard_helper
        assert self.clipboard and ch
        direction = direction.lower()
        DIRECTIONS = ("to-server", "to-client", "both", "disabled")
        if direction not in DIRECTIONS:
            raise ValueError(f"invalid direction {direction!r}, must be one of " + csv(DIRECTIONS))
        self.clipboard_direction = direction
        can_send = direction in ("to-server", "both")
        can_receive = direction in ("to-client", "both")
        ch.set_direction(can_send, can_receive)
        msg = f"clipboard direction set to {direction!r}"
        log(msg)
        self.setting_changed("clipboard-direction", direction)
        return msg

    def control_command_clipboard_limits(self, max_send: int, max_recv: int, *_args) -> str:
        ch = self._clipboard_helper
        assert self.clipboard and ch
        ch.set_limits(max_send, max_recv)
        msg = f"clipboard send limit set to {max_send}, recv limit set to {max_recv} (single copy/paste)"
        log(msg)
        self.setting_changed("clipboard-limits", {'send': max_send, 'recv': max_recv})
        return msg

    def _control_video_subregions_from_wid(self, wid: int) -> list:
        if wid not in self._id_to_window:
            raise ControlError(f"invalid window {wid}")
        video_subregions = []
        for ws in self._ws_from_args(wid):
            vs = getattr(ws, "video_subregion", None)
            if not vs:
                log.warn(f"Warning: cannot set video region enabled flag on window {wid}")
                log.warn(f" no video subregion attribute found in {type(ws)}")
                continue
            video_subregions.append(vs)
        # log("_control_video_subregions_from_wid(%s)=%s", wid, video_subregions)
        return video_subregions

    def control_command_video_region_enabled(self, wid: int, enabled: bool) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_enabled(enabled)
        return "video region %s for window %i" % (["disabled", "enabled"][int(enabled)], wid)

    def control_command_video_region_detection(self, wid: int, detection) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_detection(detection)
        return "video region detection %s for window %i" % (["disabled", "enabled"][int(detection)], wid)

    def control_command_video_region(self, wid, x: int, y: int, w: int, h: int) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_region(x, y, w, h)
        return "video region set to %s for window %i" % ((x, y, w, h), wid)

    def control_command_video_region_exclusion_zones(self, wid: int, zones) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.set_exclusion_zones(zones)
        return f"video exclusion zones set to {zones} for window {wid}"

    def control_command_reset_video_region(self, wid: int) -> str:
        for vs in self._control_video_subregions_from_wid(wid):
            vs.reset()
        return f"reset video region heuristics for window {wid}"

    def control_command_lock_batch_delay(self, wid: int, delay: int) -> None:
        for ws in self._ws_from_args(wid):
            ws.lock_batch_delay(delay)

    def control_command_unlock_batch_delay(self, wid: int) -> None:
        for ws in self._ws_from_args(wid):
            ws.unlock_batch_delay()

    def control_command_set_lock(self, lock) -> str:
        self.lock = str_to_bool(lock)
        self.setting_changed("lock", lock is not False)
        self.setting_changed("lock-toggle", lock is None)
        return f"lock set to {self.lock}"

    def control_command_set_sharing(self, sharing) -> str:
        sharing = str_to_bool(sharing)
        message = f"sharing set to {self.sharing}"
        if sharing == self.sharing:
            return message
        self.sharing = sharing
        self.setting_changed("sharing", sharing is not False)
        self.setting_changed("sharing-toggle", sharing is None)
        if not sharing:
            # there can only be one ui client now,
            # disconnect all but the first ui_client:
            # (using the 'counter' value to figure out who was first connected)
            ui_clients = {
                getattr(ss, "counter", 0): proto
                for proto, ss in tuple(self._server_sources.items()) if getattr(ss, "ui_client", False)
            }
            n = len(ui_clients)
            if n > 1:
                for c in sorted(ui_clients)[1:]:
                    proto = ui_clients[c]
                    self.disconnect_client(proto, ConnectionMessage.SESSION_BUSY, "this session is no longer shared")
                message += f", disconnected {n - 1} clients"
        return message

    def control_command_set_ui_driver(self, uuid) -> str:
        ss = [s for s in self._server_sources.values() if s.uuid == uuid]
        if not ss:
            return f"source not found for uuid {uuid!r}"
        if len(ss) > 1:
            return f"more than one source found for uuid {uuid!r}"
        self.set_ui_driver(ss)
        return f"ui-driver set to {ss}"

    def control_command_key(self, keycode_str: str, press) -> str:
        if self.readonly:
            return "command key denied by readonly mode"
        try:
            if keycode_str.startswith("0x"):
                keycode = int(keycode_str, 16)
            else:
                keycode = int(keycode_str)
        except ValueError:
            raise ControlError(f"invalid keycode specified: {keycode_str!r} (not a number)") from None
        if keycode <= 0 or keycode >= 255:
            raise ControlError(f"invalid keycode value: {keycode} (must be between 1 and 255)")
        if press is not True:
            if press in ("1", "press"):
                press = True
            elif press in ("0", "unpress"):
                press = False
            else:
                raise ControlError("if present, the press argument must be one of: " + csv(
                    ("1", "press", "0", "unpress")))
        self.fake_key(keycode, press)
        return ("pressed" if press else "unpressed") + f" {keycode}"

    def control_command_audio_output(self, *args) -> str:
        msg = []
        for csource in tuple(self._server_sources.values()):
            msg.append(f"{csource} : " + str(csource.audio_control(*args)))
        return csv(msg)

    def control_command_workspace(self, wid: int, workspace: int) -> str:
        window = self._id_to_window.get(wid)
        if not window:
            raise ControlError(f"window {wid} does not exist")
        if "workspace" not in window.get_property_names():
            raise ControlError(f"cannot set workspace on window {window}")
        if workspace < 0:
            raise ControlError(f"invalid workspace value: {workspace}")
        window.set_property("workspace", workspace)
        return f"window {wid} moved to workspace {workspace}"

    def control_command_close(self, wid: int) -> str:
        window = self._id_to_window.get(wid)
        if not window:
            raise ControlError(f"window {wid} does not exist")
        window.request_close()
        return f"requested window {window} closed"

    def control_command_delete(self, wid: int) -> str:
        window = self._id_to_window.get(wid)
        if not window:
            raise ControlError(f"window {wid} does not exist")
        window.send_delete()
        return f"requested window {window} deleted"

    def control_command_move(self, wid: int, x: int, y: int) -> str:
        window = self._id_to_window.get(wid)
        if not window:
            raise ControlError(f"window {wid} does not exist")
        ww, wh = window.get_dimensions()
        count = 0
        for source in tuple(self._server_sources.values()):
            move_resize_window = getattr(source, "move_resize_window", None)
            if move_resize_window:
                move_resize_window(wid, window, x, y, ww, wh)
                count += 1
        return f"window {wid} moved to {x},{y} for {count} clients"

    def control_command_resize(self, wid: int, w: int, h: int) -> str:
        window = self._id_to_window.get(wid)
        if not window:
            raise ControlError(f"window {wid} does not exist")
        count = 0
        for source in tuple(self._server_sources.values()):
            resize_window = getattr(source, "resize_window", None)
            if resize_window:
                resize_window(wid, window, w, h)
                count += 1
        return f"window {wid} resized to {w}x{h} for {count} clients"

    def control_command_moveresize(self, wid: int, x: int, y: int, w: int, h: int) -> str:
        window = self._id_to_window.get(wid)
        if not window:
            raise ControlError(f"window {wid} does not exist")
        count = 0
        for source in tuple(self._server_sources.values()):
            move_resize_window = getattr(source, "move_resize_window", None)
            if move_resize_window:
                move_resize_window(wid, window, x, y, w, h)
                count += 1
        return f"window {wid} moved to {x},{y} and resized to {w}x{h} for {count} clients"

    def _process_control_request(self, protocol, packet: PacketType) -> None:
        """ client sent a command request through its normal channel """
        assert len(packet) >= 2, "invalid command request packet (too small!)"
        # packet[0] = "control"
        # this may end up calling do_handle_command_request via the adapter
        code, msg = self.process_control_command(protocol, *packet[1:])
        log("command request returned: %s (%s)", code, msg)

    def init_packet_handlers(self) -> None:
        self.add_packets(f"{ServerBaseControlCommands.PREFIX}-request")
        self.add_legacy_alias("command_request", f"{ServerBaseControlCommands.PREFIX}-request")
