# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""SSH argument and forwarding decisions using explicitly resolved inputs."""

import shlex
from collections.abc import Callable
from fnmatch import fnmatch
from typing import Any

from xpra.util.parsing import parse_simple_dict, TRUE_OPTIONS


def split_ssh_command(setting: str, *, windows: bool) -> list[str]:
    return shlex.split(setting, posix=not windows)


# command and query modes that just run a single request through the proxy
# and have no session that needs the ssh agent:
# for these, agent forwarding should not be enabled by default
# (an explicit `-A`, `XPRA_SSH_AGENT=1` or a builtin backend's `agent=yes` is still honoured).
# `fnmatch` patterns are used so that whole families (ie: `list-*`, `*-info`) are covered,
# even for modes that don't support the ssh transport yet:
NO_SSH_AGENT_MODES = (
    "run", "exec", "_proxy_run", "_proxy_exec",
    "stop", "exit",
    "list", "list-*",
    "request-*",
    "setup-ssl", "show-ssl",
    "showconfig", "showsetting",
    "help",
    "info", "*-info",
    "version", "id", "sbom",
    "control",
    "print", "send-file",
)


def mode_needs_ssh_agent(mode: str) -> bool:
    # unknown / empty modes keep the historical default of enabling agent forwarding:
    return not any(fnmatch(mode, pattern) for pattern in NO_SSH_AGENT_MODES)


def get_ssh_display_attributes(ssh: list[str], ssh_option: str, mode: str, agent_forwarding: bool) -> dict[str, Any]:
    # ie: ssh=["/usr/bin/ssh", "-v"]
    ssh_cmd = ssh[0].lower()
    is_putty = ssh_cmd.endswith("plink") or ssh_cmd.endswith("plink.exe")
    is_paramiko = ssh_cmd.split(":")[0] == "paramiko"
    is_asyncssh = ssh_cmd.split(":")[0] == "asyncssh"
    desc: dict[str, Any] = {}
    if is_paramiko or is_asyncssh:
        backend = "asyncssh" if is_asyncssh else "paramiko"
        ssh[0] = backend
        desc[f"is_{backend}"] = True
        backend_config = {}
        if ssh_option.find(":") > 0:
            backend_config = parse_simple_dict(ssh_option.split(":", 1)[1])
            desc[f"{backend}-config"] = backend_config
        default_agent = "yes" if mode_needs_ssh_agent(mode) else "no"
        agent_forwarding |= backend_config.get("agent", default_agent).lower() in TRUE_OPTIONS
        backend_config["agent"] = str(agent_forwarding)
    elif is_putty:
        desc["is_putty"] = True
    desc["agent"] = agent_forwarding
    return desc


def get_ssh_args(desc, ssh=("paramiko",), prefix: str = "", *, key_path: str | None = None) -> list[str]:
    ssh_cmd = ssh[0]
    ssh_port = desc.get(f"{prefix}port", 22)
    username = desc.get(f"{prefix}username")
    password = desc.get(f"{prefix}password")
    host = desc.get(f"{prefix}host")
    if not host:
        raise RuntimeError(f"missing host from session descriptor {desc}")
    key = desc.get(f"{prefix}key")
    is_putty = any(ssh_cmd.lower().endswith(x) for x in ("plink", "plink.exe", "putty", "putty.exe"))
    is_builtin = ssh_cmd in ("asyncssh", "paramiko")
    args = []
    if password and is_putty:
        args += ["-pw", password]
    if username and not is_builtin:
        args += ["-l", username]
    if ssh_port and ssh_port != 22:
        # grr, why bother doing it different?
        if is_putty:
            args += ["-P", str(ssh_port)]
        elif not is_builtin:
            args += ["-p", str(ssh_port)]
    if not is_builtin:
        args += ["-T", host]
        if key:
            args += ["-i", key if key_path is None else key_path]
    return args


def get_ssh_proxy_args(desc, ssh, *, get_args: Callable = get_ssh_args) -> list[str]:
    is_putty = ssh[0].endswith("plink") or ssh[0].endswith("plink.exe")
    is_builtin = ssh[0] in ("asyncssh", "paramiko")
    args = []
    proxyline = ssh
    if is_putty:
        proxyline += ["-nc", "%host:%port"]
    elif not is_builtin:
        proxyline += ["-W", "%h:%p"]
    # the double quotes are in case the password has something like "&"
    proxyline += get_args(desc, ssh, prefix="proxy_")
    if is_putty:
        args += ["-proxycmd", " ".join(proxyline)]
    elif not is_builtin:
        args += ["-o", "ProxyCommand " + " ".join(proxyline)]
    return args
