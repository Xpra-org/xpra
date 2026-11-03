# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""Run a remote Xpra command with ordinary stdout, stderr and exit status."""

from codecs import getincrementaldecoder


def output_writer(stream):
    binary = getattr(stream, "buffer", None)
    decoder = getincrementaldecoder("utf8")("replace")

    def write(data: bytes) -> None:
        if binary is not None:
            binary.write(data)
            binary.flush()
        else:
            stream.write(decoder.decode(data, final=not data))
            stream.flush()

    return write


def copy_output(read, stream) -> None:
    write = output_writer(stream)
    while data := read(65536):
        write(data)
    write(b"")


def run_command(display_desc: dict) -> int:
    if display_desc.get("is_asyncssh"):
        from xpra.net.ssh.asyncssh.client import run_command as run
    elif display_desc.get("is_paramiko"):
        from xpra.net.ssh.paramiko.client import run_command as run
    else:
        from xpra.net.ssh.exec_client import run_command as run
    return run(display_desc)
