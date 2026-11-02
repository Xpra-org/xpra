#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


"""Option metadata and configuration values; no host discovery or file IO."""

import os
from typing import Any, Self
from collections.abc import Callable, Iterable


DEFAULT_BORDER: str = "auto,5:off"

OPTIONS_VALIDATION: dict[str, Callable] = {}

OPTION_TYPES: dict[str, Any] = {
    # string options:
    "encoding"          : str,
    "opengl"            : str,
    "title"             : str,
    "username"          : str,
    "password"          : str,
    "wm-name"           : str,
    "session-name"      : str,
    "dock-icon"         : str,
    "tray-icon"         : str,
    "window-icon"       : str,
    "keyboard-raw"      : bool,
    "keyboard-backend"  : str,
    "keyboard-model"    : str,
    "keyboard-layout"   : str,
    "keyboard-layouts"  : list,
    "keyboard-variant"  : str,
    "keyboard-variants" : list,
    "keyboard-options"  : str,
    "clipboard"         : str,
    "clipboard-direction" : str,
    "clipboard-filter-file" : str,
    "remote-clipboard"  : str,
    "local-clipboard"   : str,
    "pulseaudio-command": str,
    "bandwidth-limit"   : str,
    "tcp-encryption"    : str,
    "tcp-encryption-keyfile": str,
    "encryption"        : str,
    "encryption-keyfile": str,
    "pidfile"           : str,
    "mode"              : str,
    "ssh"               : str,
    "systemd-run"       : str,
    "systemd-run-args"  : str,
    "system-proxy-socket" : str,
    "chdir"             : str,
    "xvfb"              : str,
    "socket-dir"        : str,
    "sessions-dir"      : str,
    "mmap"              : str,
    "log-dir"           : str,
    "log-file"          : str,
    "border"            : str,
    "window-close"      : str,
    "min-size"          : str,
    "max-size"          : str,
    "desktop-scaling"   : str,
    "refresh-rate"      : str,
    "display"           : str,
    "download-path"     : str,
    "open-command"      : str,
    "remote-logging"    : str,
    "lpadmin"           : str,
    "lpinfo"            : str,
    "add-printer-options" : list,
    "pdf-printer"       : str,
    "postscript-printer": str,
    "debug"             : str,
    "input-method"      : str,
    "video-scaling"     : str,
    "video"             : bool,
    "audio"             : bool,
    "microphone"        : str,
    "speaker"           : str,
    "audio-source"      : str,
    "audio-sink"        : str,
    "html"              : str,
    "http-scripts"      : str,
    "http-origin"       : str,
    "socket-permissions": str,
    "exec-wrapper"      : str,
    "dbus"              : str,
    "dbus-launch"       : str,
    "webcam"            : str,
    "pointer"           : str,
    "middle-click"      : bool,
    "mousewheel"        : str,
    "input-capture"     : str,
    "input-devices"     : str,
    "shortcut-modifiers": str,
    "open-files"        : str,
    "open-url"          : str,
    "file-transfer"     : str,
    "printing"          : str,
    "headerbar"         : str,
    "seccomp"           : str,
    "landlock"          : str,
    "challenge-handlers": list,
    # ssl options:
    "ssl"               : str,
    "ssl-key"           : str,
    "ssl-key-password"  : str,
    "ssl-cert"          : str,
    "ssl-protocol"      : str,
    "ssl-ca-certs"      : str,
    "ssl-ca-data"       : str,
    "ssl-ciphers"       : str,
    "ssl-client-verify-mode"   : str,
    "ssl-server-verify-mode"   : str,
    "ssl-verify-flags"  : str,
    "ssl-check-hostname": bool,
    "ssl-server-hostname" : str,
    "ssl-options"       : str,
    "backend"           : str,
    # int options:
    "displayfd"         : int,
    "pings"             : int,
    "quality"           : int,
    "min-quality"       : int,
    "speed"             : int,
    "min-speed"         : int,
    "compression_level" : int,
    "dpi"               : int,
    "file-size-limit"   : str,
    "idle-timeout"      : int,
    "server-idle-timeout" : int,
    "sync-xvfb"         : int,
    "pixel-depth"       : int,
    "uid"               : int,
    "gid"               : int,
    "min-port"          : int,
    "rfb-upgrade"       : int,
    "rdp-upgrade"       : bool,
    # float options:
    "auto-refresh-delay": float,
    # boolean options:
    "minimal"           : bool,
    "daemon"            : bool,
    "start-via-proxy"   : bool,
    "attach"            : bool,
    "attach-urls"       : str,
    "use-display"       : str,
    "resize-display"    : str,
    "reconnect"         : bool,
    "tray"              : str,
    "pulseaudio"        : bool,
    "mmap-group"        : str,
    "readonly"          : bool,
    "keyboard-sync"     : bool,
    "cursors"           : bool,
    "bell"              : bool,
    "notifications"     : bool,
    "xsettings"         : str,
    "gsettings-sync"    : str,
    "system-tray"       : bool,
    "sharing"           : str,
    "lock"              : bool,
    "delay-tray"        : bool,
    "windows"           : bool,
    "terminate-children": bool,
    "exit-with-children": bool,
    "exit-with-client"  : bool,
    "exit-with-windows" : bool,
    "exit-ssh"          : bool,
    "dbus-control"      : bool,
    "av-sync"           : bool,
    "mdns"              : bool,
    "swap-keys"         : bool,
    "commands"          : bool,
    "control"           : bool,
    "shell"             : bool,
    "http"              : bool,
    "start-new-commands": bool,
    "proxy-start-sessions": bool,
    "session-registry"  : str,
    "desktop-fullscreen": bool,
    "forward-xdg-open"  : bool,
    "modal-windows"     : bool,
    "bandwidth-detection" : bool,
    "ssl-upgrade"       : bool,
    "websocket-upgrade" : bool,
    "ssh-upgrade"       : bool,
    "splash"            : bool,
    "gstreamer"         : bool,
    # arrays of strings:
    "pulseaudio-configure-commands" : list,
    "socket-dirs"       : list,
    "client-socket-dirs" : list,
    "remote-xpra"       : list,
    "encodings"         : list,
    "video-encoders"    : list,
    "csc-modules"       : list,
    "video-decoders"    : list,
    "speaker-codec"     : list,
    "microphone-codec"  : list,
    "compressors"       : list,
    "packet-encoders"   : list,
    "key-shortcut"      : list,
    "source"            : list,
    "source-start"      : list,
    "start"             : list,
    "start-late"        : list,
    "start-child"       : list,
    "start-child-late"  : list,
    "start-after-connect"       : list,
    "start-child-after-connect" : list,
    "start-on-connect"          : list,
    "start-child-on-connect"    : list,
    "start-on-disconnect"       : list,
    "start-child-on-disconnect" : list,
    "start-on-last-client-exit" : list,
    "start-child-on-last-client-exit"   : list,
    "bind"              : list,
    "bind-vsock"        : list,
    "bind-tcp"          : list,
    "bind-ws"           : list,
    "bind-wss"          : list,
    "bind-ssl"          : list,
    "bind-ssh"          : list,
    "bind-rfb"          : list,
    "bind-rdp"          : list,
    "bind-quic"         : list,
    "register"          : list,
    "auth"              : list,
    "vsock-auth"        : list,
    "tcp-auth"          : list,
    "ws-auth"           : list,
    "wss-auth"          : list,
    "ssl-auth"          : list,
    "ssh-auth"          : list,
    "rfb-auth"          : list,
    "rdp-auth"          : list,
    "quic-auth"         : list,
    "password-file"     : list,
    "start-env"         : list,
    "env"               : list,
}


# in the options list, available in session files,
# but not on the command line:
NON_COMMAND_LINE_OPTIONS : list[str] = [
    "mode",
    "wm-name",
    "download-path",
    "display",
    "pdf-printer",
    "postscript-printer",
    "add-printer-options",
]

START_COMMAND_OPTIONS : list[str] = [
    "start", "start-child",
    "start-late", "start-child-late",
    "start-after-connect", "start-child-after-connect",
    "start-on-connect", "start-child-on-connect",
    "start-on-disconnect", "start-child-on-disconnect",
    "start-on-last-client-exit", "start-child-on-last-client-exit",
]
BIND_OPTIONS : list[str] = [
    "bind", "bind-tcp", "bind-ssl", "bind-ws", "bind-wss", "bind-vsock", "bind-rfb", "bind-rdp", "bind-quic",
]

# keep track of the options added since v5,
# so we can generate command lines that work with older supported versions:
OPTIONS_ADDED_SINCE_V5: list[str] = [
    "minimal", "dbus", "gstreamer",
    "keyboard-backend", "keyboard-model",
    "bind-rdp", "rdp-auth", "rdp-upgrade",
    "audio-sink",
]
OPTIONS_COMPAT_NAMES: dict[str, str] = {
    "--compression_level=": "-z"
}

CLIENT_OPTIONS: list[str] = [
    "title", "username", "password", "session-name",
    "dock-icon", "tray-icon", "window-icon",
    "clipboard", "clipboard-direction", "clipboard-filter-file",
    "remote-clipboard", "local-clipboard",
    "tcp-encryption", "tcp-encryption-keyfile", "encryption", "encryption-keyfile",
    "systemd-run", "systemd-run-args",
    "socket-dir", "socket-dirs", "client-socket-dirs",
    "border", "window-close", "min-size", "max-size", "desktop-scaling",
    "file-transfer", "file-size-limit", "download-path",
    "open-command", "open-files", "printing", "open-url",
    "headerbar",
    "splash",
    "challenge-handlers",
    "remote-logging",
    "lpadmin", "lpinfo",
    "debug",
    "microphone", "speaker", "audio-source", "audio-sink",
    "microphone-codec", "speaker-codec",
    "mmap", "encodings", "encoding",
    "quality", "min-quality", "speed", "min-speed",
    "compression_level",
    "dpi", "video-scaling", "auto-refresh-delay",
    "webcam", "mousewheel", "pointer", "middle-click", "input-capture", "input-devices", "shortcut-modifiers", "pings",
    "tray", "keyboard-sync", "cursors", "bell", "notifications",
    "xsettings", "gsettings-sync", "system-tray", "sharing", "lock",
    "delay-tray", "windows", "readonly",
    "av-sync", "swap-keys",
    "opengl",
    "start-new-commands",
    "desktop-fullscreen",
    "video-encoders", "csc-modules", "video-decoders",
    "compressors", "packet-encoders",
    "key-shortcut",
    "env",
    "ssh",
]

CLIENT_ONLY_OPTIONS: list[str] = [
    "username", "swap-keys", "dock-icon",
    "tray", "delay-tray", "tray-icon",
    "attach",
    "attach-urls",
    "reconnect",
    "audio-sink",
    "input-capture",
]

# options that clients can pass to the proxy
# and which will be forwarded to the new proxy instance process:
PROXY_START_OVERRIDABLE_OPTIONS: list[str] = [
    "env", "start-env", "chdir",
    "dpi",
    "encoding", "encodings",
    "quality", "min-quality", "speed", "min-speed",
    # "auto-refresh-delay",    float!
    # no corresponding command line option:
    # "wm-name", "download-path",
    "compression_level", "video-scaling",
    "title", "session-name",
    "clipboard", "clipboard-direction", "clipboard-filter-file",
    "input-method",
    "video",
    "audio", "microphone", "speaker", "audio-source", "pulseaudio",
    "idle-timeout", "server-idle-timeout",
    "use-display",
    "resize-display", "dpi", "pixel-depth",
    "readonly", "keyboard-sync", "cursors", "bell", "notifications", "xsettings", "gsettings-sync",
    "system-tray", "sharing", "lock", "windows", "webcam", "html", "http-scripts",
    "terminate-children", "exit-with-children", "exit-with-client", "exit-with-windows",
    "av-sync",
    "forward-xdg-open", "modal-windows", "bandwidth-detection",
    "ssh-upgrade",
    "splash",
    "gstreamer",
    "printing", "file-transfer", "open-command", "open-files", "open-url", "start-new-commands",
    "mmap", "mmap-group", "mdns",
    "auth", "vsock-auth", "tcp-auth", "ws-auth", "wss-auth", "ssl-auth", "ssh-auth", "rfb-auth", "rdp-auth", "quic-auth",
    "bind", "bind-vsock", "bind-tcp", "bind-ssl", "bind-ws", "bind-wss", "bind-ssh", "bind-rfb", "bind-rdp", "bind-quic",
    "rfb-upgrade", "rdp-upgrade", "bandwidth-limit",
    "start", "start-child",
    "start-late", "start-child-late",
    "source", "source-start",
    "start-after-connect", "start-child-after-connect",
    "start-on-connect", "start-child-on-connect",
    "start-on-disconnect", "start-child-on-disconnect",
    "start-on-last-client-exit", "start-child-on-last-client-exit",
    "sessions-dir",
]
tmp: str = os.environ.get("XPRA_PROXY_START_OVERRIDABLE_OPTIONS", "")
if tmp:
    PROXY_START_OVERRIDABLE_OPTIONS = tmp.split(",")
del tmp


CLONES: dict[str, str] = {}

# these options should not be specified in config files:
NO_FILE_OPTIONS = ("daemon", )
LEGACY_OPTIONS = ("fake-xinerama", "dbus-proxy", "proxy-video-encoders")
DISCARD_OPTIONS = NO_FILE_OPTIONS + LEGACY_OPTIONS

# URLs (ie: "xpra+tcp://host:port/?param=value") are untrusted input:
# they can come from a clicked link, a web page, a QR code, etc.
# Only a small allow-list of harmless display / connection preferences
# may be set this way - everything else (commands, environment, file paths,
# authentication, encryption, listening sockets, ...) could be abused to
# achieve code execution, MITM or information disclosure on the client.
# This is an allow-list on purpose: anything not listed here is rejected,
# so newly added options are denied by default.
# The `attach-urls` option controls how URLs are handled:
# `yes` allows the options listed below, `strict` ignores all of them
# and only uses the address, `no` rejects URLs altogether.
URL_SAFE_OPTIONS: tuple[str, ...] = (
    # encoding / picture quality:
    "encoding", "encodings",
    "quality", "min-quality", "speed", "min-speed",
    "compression_level", "video-scaling", "auto-refresh-delay", "refresh-rate",
    "opengl", "dpi", "desktop-scaling",
    # window appearance:
    "title", "session-name", "border", "headerbar", "splash",
    "min-size", "max-size", "windows", "modal-windows", "desktop-fullscreen",
    # input / pointer:
    "mousewheel", "middle-click", "pointer", "input-capture", "shortcut-modifiers", "key-shortcut", "swap-keys",
    "keyboard-sync",
    # benign feature toggles:
    "clipboard", "clipboard-direction",
    "cursors", "bell", "notifications", "tray",
    "sharing", "lock", "readonly", "av-sync",
    # connection:
    "username", "password", "reconnect", "pings",
)
# one could conceivably want to add `ssl-ca-data` or `ssl-server-verify-mode` here,
# but this could be abused to connect to malicious servers...


class XpraConfig:
    def __repr__(self):
        return f"XpraConfig({self.__dict__})"

    def clone(self) -> Self:
        c = XpraConfig()
        c.__dict__ = dict(self.__dict__)
        return c


def name_to_field(name: str) -> str:
    return name.replace("-", "_")


def remove_dupes(seq: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    # note: `x not in seen and not seen.add(x)` rather than the more common
    # `not (x in seen or seen.add(x))`: Cython 3.3.0 miscompiles the latter
    # inside a comprehension filter (it gets evaluated to a constant)
    return [x for x in seq if x not in seen and not seen.add(x)]


def dict_to_config(options) -> XpraConfig:
    config = XpraConfig()
    for k,v in options.items():
        setattr(config, name_to_field(k), v)
    return config
