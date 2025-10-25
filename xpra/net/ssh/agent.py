# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Iterable

from xpra.util.io import is_socket
from xpra.log import Logger

log = Logger("server", "ssh")


def ssh_dir_path(session_dir: str = os.environ.get("XPRA_SESSION_DIR", "")) -> str:
    return os.path.join(session_dir, "ssh")


def setup_ssh_auth_sock(session_dir: str) -> str:
    # the 'ssh' dir contains agent socket symlinks to the real agent socket,
    # so we can just update the "agent" symlink
    # which is the one that applications are told to use
    ssh_dir = ssh_dir_path(session_dir)
    if not os.path.exists(ssh_dir):
        os.mkdir(ssh_dir, 0o700)
    # ie: "/run/user/1000/xpra/10/ssh/agent"
    agent_sockpath = get_ssh_agent_path("agent")
    # the current value from the environment:
    # ie: "SSH_AUTH_SOCK=/tmp/ssh-XXXX4KyFhe/agent.726992"
    # or "SSH_AUTH_SOCK=/run/user/1000/keyring/ssh"
    cur_sockpath = os.environ.pop("SSH_AUTH_SOCK", "")
    # ie: "/run/user/1000/xpra/10/ssh/agent.default"
    agent_default_sockpath = get_ssh_agent_path("agent.default")
    if os.path.islink(agent_default_sockpath):
        if not os.path.exists(agent_default_sockpath):
            # remove dead symlink
            os.unlink(agent_default_sockpath)
    elif os.path.exists(agent_default_sockpath):
        raise RuntimeError(f"{agent_default_sockpath!r} already exists but it is not a symbolic link")
    if cur_sockpath and cur_sockpath != agent_sockpath and not os.path.exists(agent_default_sockpath):
        # the current agent socket will be the default:
        # ie: "agent.default" -> "/run/user/1000/keyring/ssh"
        os.symlink(cur_sockpath, agent_default_sockpath)
    set_ssh_agent()
    return agent_sockpath


def get_ssh_agent_path(filename: str, session_dir: str = os.environ.get("XPRA_SESSION_DIR", "")) -> str:
    ssh_dir = ssh_dir_path(session_dir)
    if "/" in filename or ".." in filename:
        raise ValueError(f"illegal characters found in ssh agent filename {filename!r}")
    return os.path.join(ssh_dir, filename or "agent.default")


def set_ssh_agent(filename: str = "") -> None:
    ssh_dir = ssh_dir_path()
    if filename and os.path.isabs(filename):
        sockpath = filename
    else:
        filename = filename or "agent.default"
        sockpath = get_ssh_agent_path(filename)
    if not os.path.exists(sockpath):
        log(f"set_ssh_agent: invalid sockpath {sockpath!r}")
        return
    agent_sockpath = os.path.join(ssh_dir, "agent")
    try:
        if os.path.islink(agent_sockpath):
            os.unlink(agent_sockpath)
        log("setting ssh agent link:")
        log(f" {filename!r} -> {agent_sockpath!r}")
        os.symlink(filename, agent_sockpath)
    except OSError as e:
        log(f"set_ssh_agent({filename})", exc_info=True)
        log.error(f"Error: failed to set ssh agent socket path to {filename!r}")
        log.estr(e)


def clean_agent_socket(uuid: str = "") -> None:
    sockpath = get_ssh_agent_path(uuid)
    try:
        if os.path.exists(sockpath):
            log(f"removing ssh agent socket {sockpath!r}")
            os.unlink(sockpath)
    except OSError as e:
        log.error(f"Error: failed to remove ssh agent socket path {sockpath!r}")
        log.error(f" for uuid {uuid!r}")
        log.estr(e)


def setup_proxy_ssh_socket(
        cmdline: Iterable[str],
        auth_sock: str = os.environ.get("SSH_AUTH_SOCK", ""),
        session_dir: str = os.environ.get("XPRA_SESSION_DIR", ""),
) -> str:
    log(f"setup_proxy_ssh_socket({cmdline}, {auth_sock!r}")
    # this is the socket path that the ssh client wants us to use:
    # ie: "SSH_AUTH_SOCK=/tmp/ssh-XXXX4KyFhe/agent.726992"
    if not auth_sock or not os.path.exists(auth_sock) or not is_socket(auth_sock):
        log(f"setup_proxy_ssh_socket invalid SSH_AUTH_SOCK={auth_sock!r}")
        return ""
    if not session_dir or not os.path.exists(session_dir) or not os.path.isdir(session_dir):
        log(f"setup_proxy_ssh_socket invalid session_dir={session_dir!r}")
        return ""
    # locate the ssh agent uuid,
    # which is used to derive the agent path symlink
    # that the server will want to use for this connection,
    # newer clients pass it to the remote proxy command process using an env var:
    agent_uuid = None
    for x in cmdline:
        if x.startswith("--env=SSH_AGENT_UUID="):
            agent_uuid = x[len("--env=SSH_AGENT_UUID="):]
            break
    # prevent illegal paths:
    if not agent_uuid or agent_uuid.find("/") >= 0 or agent_uuid.find(".") >= 0:
        log(f"setup_proxy_ssh_socket invalid SSH_AGENT_UUID={agent_uuid!r}")
        return ""
    # ie: "/run/user/$UID/xpra/$DISPLAY/ssh/$UUID
    agent_uuid_sockpath = get_ssh_agent_path(agent_uuid, session_dir)
    if os.path.exists(agent_uuid_sockpath) or os.path.islink(agent_uuid_sockpath):
        if is_socket(agent_uuid_sockpath):
            log(f"setup_proxy_ssh_socket keeping existing valid socket {agent_uuid_sockpath!r}")
            # keep the existing socket unchanged - somehow it still works?
            return agent_uuid_sockpath
        log(f"setup_proxy_ssh_socket removing invalid symlink / socket {agent_uuid_sockpath!r}")
        try:
            os.unlink(agent_uuid_sockpath)
        except OSError as e:
            log(f"os.unlink({agent_uuid_sockpath!r})", exc_info=True)
            log.error("Error: removing the broken ssh agent symlink")
            log.estr(e)
    log(f"setup_proxy_ssh_socket {agent_uuid_sockpath!r} -> {auth_sock!r}")
    try:
        os.symlink(auth_sock, agent_uuid_sockpath)
    except OSError as e:
        log(f"os.symlink({auth_sock}, {agent_uuid_sockpath})", exc_info=True)
        log.error("Error creating ssh agent socket symlink")
        log.estr(e)
        return ""
    return agent_uuid_sockpath


def setup_client_ssh_agent_socket(uuid: str, ssh_auth_sock: str) -> str:
    if not uuid:
        log("cannot setup ssh agent without client uuid")
        return ""
    # perhaps the agent sock path for this uuid already exists:
    # ie: /run/user/1000/xpra/10/$UUID
    sockpath = get_ssh_agent_path(uuid)
    log(f"get_ssh_agent_path({uuid})={sockpath}")
    if not os.path.exists(sockpath) or not is_socket(sockpath):
        if os.path.islink(sockpath):
            # dead symlink
            try:
                os.unlink(sockpath)
            except OSError as e:
                log(f"os.unlink({sockpath!r})", exc_info=True)
                log.error("Error: removing the broken ssh agent symlink")
                log.estr(e)
        # perhaps this is a local client,
        # and we can find its agent socket and create the symlink now:
        log(f"client supplied ssh-auth-sock={ssh_auth_sock}")
        if ssh_auth_sock and os.path.isabs(ssh_auth_sock) and os.path.exists(ssh_auth_sock) and is_socket(
                ssh_auth_sock):  # noqa: E501
            try:
                # ie: /run/user/1000/xpra/10/$UUID -> /tmp/ssh-XXXXvjt4hN/agent.766599
                os.symlink(ssh_auth_sock, sockpath)
            except OSError as e:
                log(f"os.symlink({ssh_auth_sock}, {sockpath})", exc_info=True)
                log.error("Error setting up ssh agent socket symlink")
                log.estr(e)
                sockpath = ""
    return sockpath
