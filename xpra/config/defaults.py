#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Lazy host discovery, supplied-value default assembly, and configuration construction."""

import os
import sys
from dataclasses import dataclass
from typing import Any
from collections.abc import Sequence
from xpra.common import noop
from xpra.config.types import CLONES, DEFAULT_BORDER, XpraConfig, dict_to_config
from xpra.config.validation import validate_config
from xpra.config.vfb import detect_xvfb_command, detect_xdummy_command
from xpra.os_util import WIN32, OSX, POSIX, getuid, getgid, get_username_for_uid


DEFAULT_NET_WM_NAME: str = os.environ.get("XPRA_NET_WM_NAME", "Xpra")
DEFAULT_POSTSCRIPT_PRINTER: str = ""
if POSIX:
    DEFAULT_POSTSCRIPT_PRINTER = os.environ.get("XPRA_POSTSCRIPT_PRINTER", "drv:///sample.drv/generic.ppd")
DEFAULT_PULSEAUDIO = False if OSX or WIN32 else None

_has_audio_support: bool | None = None
GLOBAL_DEFAULTS: dict[str, Any] | None = None


def has_audio_support() -> bool:
    global _has_audio_support
    if _has_audio_support is None:
        try:
            from importlib.util import find_spec
            _has_audio_support = bool(find_spec("xpra.audio"))
        except ImportError:
            _has_audio_support = False
    return bool(_has_audio_support)


def get_default_key_shortcuts() -> list[str]:
    return [shortcut for e, shortcut in (
        (True, "Control+Menu:toggle_keyboard_grab"),
        (True, "Shift+Menu:toggle_pointer_grab"),
        (True, "Control+Escape:dismiss_popups"),
        (not OSX, "Shift+F11:toggle_fullscreen"),
        (OSX, "Control+F11:toggle_fullscreen"),
        (True, "#+F1:show_menu"),
        (True, "Control+F1:show_window_menu"),
        (True, "#+F2:show_start_new_command"),
        (True, "#+F3:show_bug_report"),
        (True, "#+F4:quit"),
        (True, "#+F5:show_window_info"),
        (True, "#+F6:show_shortcuts"),
        (True, "#+F7:show_docs"),
        (True, "#+F8:toggle_keyboard_grab"),
        (True, "#+F9:toggle_pointer_grab"),
        (True, "#+Escape:toggle_input_capture"),
        (True, "#+F10:magic_key"),
        (True, "#+F11:show_session_info"),
        (True, "#+F12:toggle_debug"),
        (True, "#+plus:scaleup"),
        (OSX, "#+plusminus:scaleup"),
        (True, "#+minus:scaledown"),
        (True, "#+underscore:scaledown"),
        (OSX, "#+emdash:scaledown"),
        (True, "#+KP_Add:scaleup"),
        (True, "#+KP_Subtract:scaledown"),
        (True, "#+KP_Multiply:scalereset"),
        (True, "#+bar:scalereset"),
        (True, "#+question:scalingoff"),
        (OSX, "#+degree:scalereset"),
        (OSX, "meta+grave:void"),
        (OSX, "meta+shift+asciitilde:void"),
    )
        if e]


def get_default_systemd_run() -> str:
    if WIN32 or OSX:
        return "no"
    # systemd-run was previously broken in Fedora 26:
    # https://github.com/systemd/systemd/issues/3388
    # but with newer kernels, it is working again..
    # now that we test it before using it,
    # it should be safe to leave it on auto:
    return "auto"


def unexpand(path: str) -> str:
    xrd = os.environ.get("XDG_RUNTIME_DIR", "")
    if POSIX and xrd and path.startswith(xrd):
        return "$XDG_RUNTIME_DIR/" + path[len(xrd):].lstrip("/")
    home = os.environ.get("HOME", "")
    if POSIX and home and path.startswith(home):
        return "~/" + path[len(home):].lstrip("/")
    return path


def unexpand_all(paths: list[str]) -> list[str]:
    return [unexpand(x) for x in paths]


def get_default_env() -> Sequence[str]:
    if WIN32 or OSX:
        return ()
    return (
        "#silence some AT-SPI and atk-bridge warnings:",
        "NO_AT_BRIDGE=1",
    )


def get_default_start_env() -> Sequence[str]:
    if WIN32 or OSX:
        return ()
    return (
        "#avoid Ubuntu's global menu, which is a mess and cannot be forwarded:",
        "UBUNTU_MENUPROXY=",
        "QT_X11_NO_NATIVE_MENUBAR=1",
        "#fix for MainSoft's MainWin buggy window management:",
        "MWNOCAPTURE=true",
        "MWNO_RIT=true",
        "MWWM=allwm",
        "#tell GTK4 applications to use the software Gsk renderer to avoid freezes and crashes:",
        "#(if using a real GPU, you may want to switch to `vulkan` or `opengl` instead)",
        "GSK_RENDERER=cairo",
        "#GTK seems to default to using AT-SPI and atk-bridge, which triggers warnings:",
        "#(see issue #2318)",
        "GTK_A11Y=none",
        "#force Qt applications to use X11 so we can intercept them:",
        "QT_QPA_PLATFORM=xcb",
        "#disable Qt scaling:",
        "QT_AUTO_SCREEN_SET_FACTOR=0",
        "QT_SCALE_FACTOR=1",
        "#overlay scrollbars complicate things:",
        "GTK_OVERLAY_SCROLLING=0",
        "#some versions of GTK3 honour this option, sadly not all:",
        "GTK_CSD=0",
        "#use this to make SDL video windows minimize on focus loss:",
        "#SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=1",
    )


def get_default_seccomp() -> str:
    if sys.platform.startswith("linux"):
        return "default"
    return "no"


@dataclass(frozen=True, slots=True)
class DefaultsContext:
    """Resolved inputs to build_defaults(); collecting them performs host discovery."""
    win32: bool
    osx: bool
    posix: bool
    wm_name: str
    border: str
    postscript_printer: str
    pulseaudio: bool | None
    systemd_run: str
    system_proxy_socket: str
    xvfb: str
    xdummy: str
    sessions_dir: str
    download_dir: str
    seccomp: str
    uid: int
    gid: int
    audio_support: bool
    socket_dirs: list[str]
    client_socket_dirs: list[str]
    remote_xpra: Sequence[str]
    key_shortcuts: list[str]
    start_env: Sequence[str]
    env: Sequence[str]


def collect_defaults_context() -> DefaultsContext:
    """Resolve platform paths, display commands, and optional audio support lazily."""
    from xpra.net.constants import SYSTEM_PROXY_SOCKET
    from xpra.platform.paths import (
        get_download_dir, get_remote_run_xpra_scripts,
        get_sessions_dir, get_socket_dirs, get_client_socket_dirs,
    )
    conf_dirs = [os.environ.get("XPRA_CONF_DIR", "")]
    if build_root := os.environ.get("RPM_BUILD_ROOT", ""):
        conf_dirs.append(os.path.join(build_root, "etc", "xpra"))
    bin_dir = ""
    if sys.argv:
        xpra_cmd = sys.argv[0]
        for strip in ("/usr/bin", "/bin"):
            pos = xpra_cmd.find(strip)
            if pos >= 0:
                bin_dir = xpra_cmd[:pos+len(strip)]
                root = xpra_cmd[:pos] or "/"
                conf_dirs.append(os.path.join(root, "etc", "xpra"))
                break
    if sys.prefix == "/usr":
        conf_dirs.append("/etc/xpra")
    else:
        conf_dirs.append(os.path.join(sys.prefix, "etc", "xpra"))
    try:
        conf_dirs.append(os.getcwd())
    except FileNotFoundError:
        pass
    conf_dir = ""
    for conf_dir in conf_dirs:
        if conf_dir and os.path.exists(conf_dir):
            break
    xvfb = detect_xvfb_command(conf_dir, bin_dir, warn_fn=noop)
    xdummy = detect_xdummy_command(conf_dir, bin_dir, warn_fn=noop)

    return DefaultsContext(
        win32=WIN32, osx=OSX, posix=POSIX,
        wm_name=DEFAULT_NET_WM_NAME, border=DEFAULT_BORDER,
        postscript_printer=DEFAULT_POSTSCRIPT_PRINTER, pulseaudio=DEFAULT_PULSEAUDIO,
        systemd_run=get_default_systemd_run(), system_proxy_socket=SYSTEM_PROXY_SOCKET,
        xvfb=" ".join(xvfb), xdummy=" ".join(xdummy),
        sessions_dir=get_sessions_dir(), download_dir=get_download_dir(),
        seccomp=get_default_seccomp(), uid=getuid(), gid=getgid(), audio_support=has_audio_support(),
        socket_dirs=unexpand_all(get_socket_dirs()), client_socket_dirs=unexpand_all(get_client_socket_dirs()),
        remote_xpra=get_remote_run_xpra_scripts(), key_shortcuts=get_default_key_shortcuts(),
        start_env=get_default_env(), env=get_default_start_env(),
    )


def build_defaults(context: DefaultsContext) -> dict[str, Any]:
    """Assemble defaults from supplied values without probing the host."""
    # we access the GUI when running as a MacOS server (tray, etc.)
    # and so we cannot daemonize
    CAN_DAEMONIZE = not (context.win32 or context.osx)
    SOURCE = ("/etc/profile",) if context.posix else ()
    if context.osx:
        OPEN_COMMAND = ("open",)
    elif context.win32:
        OPEN_COMMAND = ["start", "''"]
    else:
        OPEN_COMMAND = ("/usr/bin/xdg-open", )

    # noinspection PyPep8
    return {
        "encoding"          : "auto",
        "title"             : "@title@ on @hostinfo@",
        "username"          : "",
        "password"          : "",
        "wm-name"           : context.wm_name,
        "session-name"      : "",
        "dock-icon"         : "",
        "tray-icon"         : "",
        "window-icon"       : "",
        "keyboard-raw"      : False,
        "keyboard-backend"  : "",
        "keyboard-model"    : "",
        "keyboard-layout"   : "",
        "keyboard-layouts"  : [],
        "keyboard-variant"  : "",
        "keyboard-variants" : [],
        "keyboard-options"  : "",
        "clipboard"         : "auto",
        "clipboard-direction" : "both",
        "clipboard-filter-file" : "",
        "remote-clipboard"  : "CLIPBOARD",
        "local-clipboard"   : "CLIPBOARD",
        "pulseaudio-command": "auto",
        "bandwidth-limit"   : "auto",
        "encryption"        : "",
        "tcp-encryption"    : "",
        "encryption-keyfile": "",
        "tcp-encryption-keyfile": "",
        "pidfile"           : "${XPRA_SESSION_DIR}/server.pid",
        "ssh"               : "auto",
        "systemd-run"       : context.systemd_run,
        "systemd-run-args"  : "",
        "system-proxy-socket" : context.system_proxy_socket,
        "xvfb"              : context.xvfb,
        "xdummy"            : context.xdummy,
        "chdir"             : "",
        "socket-dir"        : "",
        "sessions-dir"      : context.sessions_dir,
        "log-dir"           : "auto",
        "log-file"          : "server.log",
        "border"            : context.border,
        "window-close"      : "auto",
        "min-size"          : "",
        "max-size"          : "",
        "desktop-scaling"   : "on",
        "refresh-rate"      : "auto",
        "display"           : "",
        "download-path"     : context.download_dir,
        "open-command"      : " ".join(OPEN_COMMAND),
        "remote-logging"    : "both",
        "lpadmin"           : "/usr/sbin/lpadmin",
        "lpinfo"            : "/usr/sbin/lpinfo",
        "add-printer-options" : ["-u allow:$USER", "-E", "-o printer-is-shared=false"],
        "pdf-printer"       : "",
        "postscript-printer": context.postscript_printer,
        "debug"             : "",
        "seccomp"           : context.seccomp,
        "landlock"          : "no",
        "input-method"      : "auto",
        "audio-source"      : "",
        "audio-sink"        : "auto",
        "html"              : "auto",
        "http-scripts"      : "all",
        "http-origin"       : "auto",
        "socket-permissions": "600",
        "exec-wrapper"      : "",
        "dbus"              : ["no", "yes"][context.posix and not context.osx],
        "dbus-launch"       : "dbus-launch --sh-syntax --close-stderr",
        "webcam"            : ["auto", "no"][context.osx or context.win32],
        "mousewheel"        : ["on", "invert-x"][context.osx],
        "pointer"           : "auto",
        "middle-click"      : True,
        "input-capture"     : "no",
        "input-devices"     : "auto",
        "shortcut-modifiers": "auto",
        "open-files"        : "auto",
        "open-url"          : "auto",
        "file-transfer"     : "auto",
        "printing"          : "yes",
        "headerbar"         : ["auto", "no"][context.osx or context.win32],
        "challenge-handlers": ["all"],
        # ssl options:
        "ssl"               : "auto",
        "ssl-key"           : "",
        "ssl-key-password"  : "",
        "ssl-cert"          : "",
        "ssl-protocol"      : "TLS",
        "ssl-ca-certs"      : "default",
        "ssl-ca-data"       : "",
        "ssl-ciphers"       : "DEFAULT",
        "ssl-client-verify-mode"   : "optional",
        "ssl-server-verify-mode"   : "required",
        "ssl-verify-flags"  : "X509_STRICT",
        "ssl-check-hostname": True,
        "ssl-server-hostname": "",
        "ssl-options"       : "ALL,NO_COMPRESSION",
        "backend"           : "auto",
        "quality"           : 0,
        "min-quality"       : 1,
        "speed"             : 0,
        "min-speed"         : 1,
        "compression_level" : 1,
        "dpi"               : 0,
        "file-size-limit"   : "1G",
        "idle-timeout"      : 0,
        "server-idle-timeout" : 0,
        "sync-xvfb"         : None,
        "pixel-depth"       : 0,
        "uid"               : context.uid,
        "gid"               : context.gid,
        "min-port"          : 1024,
        "rfb-upgrade"       : 5,
        "rdp-upgrade"       : False,
        "auto-refresh-delay": 0.15,
        "minimal"           : False,
        "daemon"            : CAN_DAEMONIZE,
        "start-via-proxy"   : False,
        "attach"            : None,
        "attach-urls"       : "yes",
        "use-display"       : "auto",
        "resize-display"    : ["no", "auto"][not context.osx and not context.win32],
        "reconnect"         : True,
        "tray"              : "auto",
        "pulseaudio"        : context.pulseaudio,
        "mmap"              : ["auto", "no"][context.osx or context.win32],
        "mmap-group"        : "auto",
        "video"             : True,
        "audio"             : True,
        "speaker"           : ["disabled", "on"][context.audio_support],
        "microphone"        : ["disabled", "off"][context.audio_support],
        "video-scaling"     : "auto",
        "readonly"          : False,
        "keyboard-sync"     : True,
        "displayfd"         : 0,
        "pings"             : 5,
        "cursors"           : True,
        "bell"              : True,
        "notifications"     : True,
        "xsettings"         : ["auto", "no"][int(context.osx or context.win32)],
        "gsettings-sync"    : ["auto", "no"][int(context.osx or context.win32)],
        "system-tray"       : True,
        "sharing"           : "auto",
        "lock"              : None,
        "delay-tray"        : False,
        "windows"           : True,
        "terminate-children": False,
        "exit-with-children": False,
        "exit-with-client"  : False,
        "exit-with-windows" : False,
        "commands"          : True,
        "control"           : None,
        "shell"             : False,
        "http"              : True,
        "start-new-commands": True,
        "proxy-start-sessions": True,
        "session-registry"  : "auth",
        "av-sync"           : True,
        "exit-ssh"          : True,
        "dbus-control"      : not context.win32 and not context.osx,
        "opengl"            : "no" if context.osx else "probe",
        "mdns"              : not context.win32,
        "swap-keys"         : context.osx,  # only used on osx
        "desktop-fullscreen": False,
        "forward-xdg-open"  : None,
        "modal-windows"     : False,
        "bandwidth-detection" : False,
        "ssl-upgrade"       : None,
        "websocket-upgrade" : True,
        "ssh-upgrade"       : True,
        "splash"            : None,
        "gstreamer"         : True,
        "pulseaudio-configure-commands"  : ["auto"],
        "socket-dirs"       : context.socket_dirs,
        "client-socket-dirs" : context.client_socket_dirs,
        "remote-xpra"       : context.remote_xpra,
        "encodings"         : ["all"],
        "video-encoders"    : ["all"],
        "csc-modules"       : ["all"],
        "video-decoders"    : ["all"],
        "speaker-codec"     : [],
        "microphone-codec"  : [],
        "compressors"       : ["all"],
        "packet-encoders"   : ["all"],
        "key-shortcut"      : context.key_shortcuts,
        "bind"              : ["auto"],
        "bind-vsock"        : [],
        "bind-tcp"          : [],
        "bind-ws"           : [],
        "bind-wss"          : [],
        "bind-ssl"          : [],
        "bind-ssh"          : [],
        "bind-rfb"          : [],
        "bind-rdp"          : [],
        "bind-quic"         : [],
        "register"          : [],
        "auth"              : [],
        "vsock-auth"        : [],
        "tcp-auth"          : [],
        "ws-auth"           : [],
        "wss-auth"          : [],
        "ssl-auth"          : [],
        "ssh-auth"          : [],
        "rfb-auth"          : [],
        "rdp-auth"          : [],
        "quic-auth"         : [],
        "password-file"     : [],
        "source"            : SOURCE,
        "source-start"      : [],
        "start"             : [],
        "start-late"        : [],
        "start-child"       : [],
        "start-child-late"  : [],
        "start-after-connect"       : [],
        "start-child-after-connect" : [],
        "start-on-connect"          : [],
        "start-child-on-connect"    : [],
        "start-on-disconnect"          : [],
        "start-child-on-disconnect"    : [],
        "start-on-last-client-exit" : [],
        "start-child-on-last-client-exit"   : [],
        "start-env"         : context.start_env,
        "env"               : context.env,
    }


def get_defaults() -> dict[str, Any]:
    global GLOBAL_DEFAULTS
    if GLOBAL_DEFAULTS is None:
        GLOBAL_DEFAULTS = build_defaults(collect_defaults_context())
    return GLOBAL_DEFAULTS


def make_defaults_struct(extras_defaults=None, extras_types=None, extras_validation=None,
                         username="", uid=getuid(), gid=getgid()) -> XpraConfig:
    return do_make_defaults_struct(extras_defaults or {}, extras_types or {}, extras_validation or {},
                                   username, uid, gid)


def do_make_defaults_struct(extras_defaults: dict, extras_types: dict, extras_validation: dict,
                            username:str, uid: int, gid: int) -> XpraConfig:
    # populate config with default values:
    if not username and uid:
        username = get_username_for_uid(uid)
    from xpra.config.io import read_xpra_defaults
    defaults = read_xpra_defaults(username, uid, gid)
    return dict_to_validated_config(defaults, extras_defaults, extras_types, extras_validation)


def dict_to_validated_config(d: dict, extras_defaults=None, extras_types=None, extras_validation=None) -> XpraConfig:
    options = get_defaults().copy()
    if extras_defaults:
        options.update(extras_defaults)
    # parse config:
    validated = validate_config(d, extras_types=extras_types, extras_validation=extras_validation)
    options.update(validated)
    for k,v in CLONES.items():
        if k in options:
            options[v] = options[k]
    return dict_to_config(options)
