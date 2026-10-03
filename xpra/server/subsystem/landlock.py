# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.exit_codes import ExitCode
from xpra.log import Logger
from xpra.os_util import LINUX
from xpra.scripts.config import InitException, InitExit
from xpra.server.subsystem.stub import StubSubsystem

log = Logger("landlock")


class LandLock(StubSubsystem):
    """Confine the server after its sockets and authentication resources are ready."""
    __slots__ = ("abi", "enforced", "mode", "mmap_paths", "auth_paths", "temp_dir", "temp_dir_owner")
    PREFIX = "landlock"

    def __init__(self, server=None):
        super().__init__(server)
        self.mode = "no"
        self.mmap_paths: tuple[str, ...] = ()
        self.auth_paths: tuple[str, ...] = ()
        self.abi = 0
        self.enforced = False
        self.temp_dir = ""
        self.temp_dir_owner = 0

    def init(self, opts) -> None:
        self.mode = opts.landlock or "no"
        if LINUX and self.mode != "no":
            try:
                from xpra.platform.posix.security import get_landlock_auth_paths, get_landlock_mmap_paths
                self.auth_paths = get_landlock_auth_paths(opts)
                self.mmap_paths = get_landlock_mmap_paths(opts.mmap or "")
            except (ImportError, OSError, ValueError) as e:
                raise InitExit(ExitCode.FAILURE, f"failed to initialize server Landlock: {e}") from None

    def setup(self) -> None:
        if not LINUX or self.mode == "no" or self.enforced:
            return
        try:
            # The session bus must create its socket before confinement.
            if dbus := self.get_subsystem("dbus"):
                if dbus.enabled and not dbus.env:
                    dbus.init_dbus_env()
            from xpra.platform.posix.menu_helper import prepare_menu_icon_cache_dir
            from xpra.platform.posix.security import enforce_landlock
            session_dir = os.environ.get("XPRA_SESSION_DIR", "")
            write_paths = (session_dir, prepare_menu_icon_cache_dir()) + self.mmap_paths
            socket_dirs = [os.path.dirname(sock.address) for sock in self.server.sockets
                           if sock.socktype == "socket" and not sock.address.startswith("@")]
            auth_paths = self.auth_paths + self.get_auth_paths()
            if self.mode == "strict":
                from xpra.platform.posix.security import prepare_landlock_temp_dir
                self.temp_dir, self.temp_dir_owner = prepare_landlock_temp_dir(session_dir)
            self.abi = enforce_landlock(self.mode, write_paths, read_paths=auth_paths, required_paths=auth_paths,
                                        socket_dirs=socket_dirs, cleanup_dirs=(os.path.dirname(session_dir),),
                                        temp_dir=self.temp_dir, allow_socket_creation=False)
            self.enforced = True
        except (ImportError, OSError, ValueError, InitException) as e:
            with log.trap_error("Error cleaning up after failed Landlock enforcement"):
                self.cleanup()
            raise InitExit(ExitCode.FAILURE, f"failed to restrict the server process with Landlock: {e}") from None

    def get_info(self, _proto) -> dict:
        return {LandLock.PREFIX: {
            "mode": self.mode, "enforced": self.enforced, "abi": self.abi,
            "temp-dir": self.temp_dir,
        }}

    def get_auth_paths(self) -> tuple[str, ...]:
        """Collect authentication resources selected by server initialization."""
        from xpra.auth.auth_helper import get_auth_module
        paths = []
        definitions = []
        if auth := self.get_subsystem("auth"):
            for entries in auth.auth_classes.values():
                definitions.extend(entries)
        for listener in self.server.sockets:
            options = listener.options
            for name in ("ssh-host-key", "ssl-cert", "ssl-key", "ssl-ca-certs"):
                if path := options.get(name):
                    if path not in ("default", "auto"):
                        paths.append(path)
            auth = options.get("auth", ())
            if isinstance(auth, str):
                auth = (auth,)
            definitions.extend(get_auth_module(value) for value in auth)
        for _name, _module, _cls, options in definitions:
            if filename := options.get("filename"):
                if not os.path.isabs(filename):
                    filename = os.path.join(options["exec_cwd"], filename)
                paths.append(filename)
        return tuple(paths)

    def cleanup(self) -> None:
        # Registered first, so reverse cleanup runs this after its peers and
        # before SessionFilesServer.late_cleanup removes the session directory.
        if self.temp_dir:
            from xpra.platform.posix.security import cleanup_landlock_temp_dir
            cleanup_landlock_temp_dir(self.temp_dir, self.temp_dir_owner)
            self.temp_dir = ""
            self.temp_dir_owner = 0
