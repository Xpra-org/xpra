# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from __future__ import annotations

import os
import subprocess
import hashlib
import uuid
from typing import Any, Final
from time import monotonic
from dataclasses import dataclass
from collections.abc import Callable

from xpra.util.child_reaper import getChildReaper
from xpra.os_util import POSIX, WIN32, gi_import
from xpra.util.io import umask_context
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool
from xpra.scripts.config import str_to_bool, parse_with_unit
from xpra.common import SizedBuffer
from xpra.net.common import PacketType, PacketElement
from xpra.util.stats import std_unit
from xpra.util.thread import start_thread
from xpra.log import Logger

GLib = gi_import("GLib")

printlog = Logger("printing")
filelog = Logger("file")

DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
FILE_CHUNKS_SIZE = max(0, envint("XPRA_FILE_CHUNKS_SIZE", 65536))
MAX_CONCURRENT_FILES = max(1, envint("XPRA_MAX_CONCURRENT_FILES", 10))
PRINT_JOB_TIMEOUT = max(60, envint("XPRA_PRINT_JOB_TIMEOUT", 3600))
SEND_REQUEST_TIMEOUT = max(300, envint("XPRA_SEND_REQUEST_TIMEOUT", 3600))
CHUNK_TIMEOUT = 10 * 1000

MIMETYPE_EXTS: dict[str, str] = {
    "application/postscript": "ps",
    "application/pdf": "pdf",
    "raw": "raw",
}

DENY: Final[int] = 0
ACCEPT: Final[int] = 1  # the file / URL will be sent
OPEN: Final[int] = 2  # don't send, open on sender


def osclose(fd: int) -> None:
    try:
        os.close(fd)
    except OSError as e:
        filelog("os.close(%s)", fd, exc_info=True)
        filelog.error("Error closing file download:")
        filelog.estr(e)


def basename(filename: str) -> str:
    # we can't use os.path.basename,
    # because the remote end may have sent us a filename
    # which is using a different pathsep
    tmp = filename
    for sep in ("\\", "/", os.sep):
        i = tmp.rfind(sep) + 1
        tmp = tmp[i:]
    filename = tmp
    if WIN32:  # pragma: no cover
        # many characters aren't allowed at all on win32:
        tmp = ""
        for char in filename:
            if ord(char) < 32 or char in ("<", ">", ":", "\"", "|", "?", "*"):
                char = "_"
            tmp += char
    return tmp


def safe_open_download_file(basefilename: str, mimetype: str) -> tuple[str, int]:
    from xpra.platform.paths import get_download_dir  # pylint: disable=import-outside-toplevel
    dd = os.path.expanduser(get_download_dir())
    filename = os.path.abspath(os.path.join(dd, basename(basefilename)))
    ext = MIMETYPE_EXTS.get(mimetype)
    if ext and not filename.endswith("." + ext):
        # on some platforms (win32),
        # we want to force an extension
        # so that the file manager can display them properly when you double-click on them
        filename += "." + ext
    # make sure we use a filename that does not exist already:
    root, ext = os.path.splitext(filename)
    base = 0
    while os.path.exists(filename):
        filelog(f"cannot save file as {filename!r}: file already exists")
        base += 1
        filename = f"{root}-{base}{ext}"
    filelog("safe_open_download_file(%s, %s) will use %r", basefilename, mimetype, filename)
    flags = os.O_CREAT | os.O_RDWR | os.O_EXCL
    try:
        flags |= os.O_BINARY  # @UndefinedVariable (win32 only)
    except AttributeError:
        pass
    with umask_context(0o133):
        fd = os.open(filename, flags)
    filelog(f"using {filename=!r}, {fd=}")
    return filename, fd


@dataclass
class ReceiveChunkState:
    start: float
    fd: int
    filename: str
    mimetype: str
    printit: bool
    openit: bool
    filesize: int
    options: typedict
    digest: hashlib._Hash | None
    written: int
    cancelled: bool
    send_id: str
    timer: int
    chunk: int


@dataclass
class SendChunkState:
    start: float
    data: bytes
    chunk_size: int
    timer: int
    chunk: int


@dataclass
class SendPendingData:
    datatype: str
    url: str
    mimetype: str
    data: bytes
    filesize: int
    printit: bool
    openit: bool
    options: dict


class FileTransferAttributes:

    def __init__(self):
        self.init_attributes()

    def init_opts(self, opts, can_ask=True) -> None:
        # get the settings from a config object
        self.init_attributes(opts.file_transfer, opts.file_size_limit,
                             opts.printing, opts.open_files, opts.open_url, opts.open_command, can_ask)

    def init_attributes(self, file_transfer="no", file_size_limit="1G", printing="no",
                        open_files="no", open_url="no", open_command=None, can_ask=True) -> None:
        filelog("file transfer: init_attributes%s",
                (file_transfer, file_size_limit, printing, open_files, open_url, open_command, can_ask))

        def pask(v) -> bool:
            return v.lower() in ("ask", "auto")

        fta = pask(file_transfer)
        self.file_transfer_ask = fta and can_ask
        self.file_transfer = fta or str_to_bool(file_transfer)
        self.file_size_limit = parse_with_unit("file-size-limit", file_size_limit, "B", min_value=0) or 0
        self.file_chunks = FILE_CHUNKS_SIZE
        pa = pask(printing)
        self.printing_ask = pa and can_ask
        self.printing = pa or str_to_bool(printing)
        ofa = pask(open_files)
        self.open_files_ask = ofa and can_ask
        self.open_files = ofa or str_to_bool(open_files)
        # FIXME: command line options needed here:
        oua = pask(open_url)
        self.open_url_ask = oua and can_ask
        self.open_url = oua or str_to_bool(open_url)
        self.file_ask_timeout = SEND_REQUEST_TIMEOUT
        self.open_command = open_command
        self.files_requested: dict[str, bool] = {}
        self.files_accepted: dict[str, bool] = {}
        self.file_request_callback: dict[str, Callable[[str, int], None]] = {}
        filelog("file transfer attributes=%s", self.get_file_transfer_features())

    def get_file_transfer_features(self) -> dict[str, Any]:
        # used in hello packets,
        # duplicated with namespace (old caps to be removed in v6)
        return {
            "file-transfer": self.file_transfer,
            "file-transfer-ask": self.file_transfer_ask,
            "max-file-size": self.file_size_limit,
            "file-chunks": self.file_chunks,
            "open-files": self.open_files,
            "open-files-ask": self.open_files_ask,
            "printing": self.printing,
            "printing-ask": self.printing_ask,
            "open-url": self.open_url,
            "open-url-ask": self.open_url_ask,
            "file-ask-timeout": self.file_ask_timeout,
            # v5 onwards can use a proper namespace:
            "file": self.get_file_transfer_info(),
        }

    def get_info(self) -> dict[str, Any]:
        return self.get_file_transfer_info()

    def get_file_transfer_info(self) -> dict[str, Any]:
        # slightly different from above... for legacy reasons
        # this one is used for get_info() in a proper "file." namespace from base.py
        return {
            "enabled": self.file_transfer,
            "ask": self.file_transfer_ask,
            "size-limit": self.file_size_limit,
            "chunks": self.file_chunks,
            "open": self.open_files,
            "open-ask": self.open_files_ask,
            "open-url": self.open_url,
            "open-url-ask": self.open_url_ask,
            "printing": self.printing,
            "printing-ask": self.printing_ask,
            "ask-timeout": self.file_ask_timeout,
        }


def digest_mismatch(filename: str, digest, expected_digest) -> None:
    filelog.error(f"Error: data does not match, invalid {digest.name} file digest")
    filelog.error(f" for {filename!r}")
    filelog.error(f" received {digest.hexdigest()}")
    filelog.error(f" expected {expected_digest}")


def get_open_env() -> dict[str, str]:
    env = os.environ.copy()
    # prevent loops:
    env["XPRA_XDG_OPEN"] = "1"
    return env


class FileTransferHandler(FileTransferAttributes):
    """
        Utility class for receiving files and optionally printing them,
        used by both clients and server to share the common code and attributes
    """

    def init_attributes(self, *args) -> None:
        super().init_attributes(*args)
        self.remote_file_transfer = False
        self.remote_file_transfer_ask = False
        self.remote_printing = False
        self.remote_printing_ask = False
        self.remote_open_files = False
        self.remote_open_files_ask = False
        self.remote_open_url = False
        self.remote_open_url_ask = False
        self.remote_file_ask_timeout = SEND_REQUEST_TIMEOUT
        self.remote_file_size_limit = 0
        self.remote_file_chunks = 0
        self.pending_send_data: dict[str, SendPendingData] = {}
        self.pending_send_data_timers: dict[str, int] = {}
        self.send_chunks_in_progress: dict[str, SendChunkState] = {}
        self.receive_chunks_in_progress: dict[str, ReceiveChunkState] = {}
        self.file_descriptors: set[int] = set()

    def cleanup(self) -> None:
        for t in self.pending_send_data_timers.values():
            GLib.source_remove(t)
        self.pending_send_data_timers = {}
        for v in self.receive_chunks_in_progress.values():
            GLib.source_remove(v.timer)
        self.receive_chunks_in_progress = {}
        for x in tuple(self.file_descriptors):
            try:
                os.close(x)
            except OSError as e:
                filelog(f"os.close({x}) {e}")
        self.file_descriptors = set()
        self.init_attributes()

    def parse_file_transfer_caps(self, c) -> None:
        fc = typedict(c.dictget("file") or {})
        filelog("parse_file_transfer_caps: %s", fc)
        # v5 with "file" namespace:
        self.remote_file_transfer = fc.boolget("enabled")
        self.remote_file_transfer_ask = fc.boolget("ask")
        self.remote_printing = fc.boolget("printing")
        self.remote_printing_ask = fc.boolget("printing-ask")
        self.remote_open_files = fc.boolget("open")
        self.remote_open_files_ask = fc.boolget("open-ask")
        self.remote_open_url = fc.boolget("open-url")
        self.remote_open_url_ask = fc.boolget("open-url-ask")
        self.remote_file_ask_timeout = fc.intget("ask-timeout")
        self.remote_file_size_limit = fc.intget("max-file-size") or fc.intget("size-limit")
        self.remote_file_chunks = max(0, fc.intget("chunks"))
        self.dump_remote_caps()

    def dump_remote_caps(self) -> None:
        filelog("file transfer remote caps:")
        filelog(" file-transfer=%-5s   (ask=%s)", self.remote_file_transfer, self.remote_file_transfer_ask)
        filelog(" printing=%-5s        (ask=%s)", self.remote_printing, self.remote_printing_ask)
        filelog(" open-files=%-5s      (ask=%s)", self.remote_open_files, self.remote_open_files_ask)
        filelog(" open-url=%-5s        (ask=%s)", self.remote_open_url, self.remote_open_url_ask)
        filelog(" file-size-limit=%s", self.remote_file_size_limit)

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["remote"] = {
            "file-transfer": self.remote_file_transfer,
            "file-transfer-ask": self.remote_file_transfer_ask,
            "file-size-limit": self.remote_file_size_limit,
            "file-chunks": self.remote_file_chunks,
            "open-files": self.remote_open_files,
            "open-files-ask": self.remote_open_files_ask,
            "open-url": self.remote_open_url,
            "open-url-ask": self.remote_open_url_ask,
            "printing": self.remote_printing,
            "printing-ask": self.remote_printing_ask,
            "file-ask-timeout": self.remote_file_ask_timeout,
        }
        return info

    def _check_chunk_receiving(self, chunk_id: str, chunk_no: int) -> None:
        chunk_state = self.receive_chunks_in_progress.get(chunk_id)
        filelog("_check_chunk_receiving(%s, %s) chunk_state=%s", chunk_id, chunk_no, chunk_state)
        if not chunk_state:
            # transfer not found
            return
        if chunk_state.cancelled:
            # transfer has been cancelled
            return
        chunk_state.timer = 0  # this timer has been used
        if chunk_state.chunk == chunk_no:
            filelog.error(f"Error: chunked file transfer f{chunk_id} timed out")
            self.receive_chunks_in_progress.pop(chunk_id, None)

    def cancel_download(self, send_id: str, message="Cancelled") -> None:
        filelog("cancel_download(%s, %s)", send_id, message)
        for chunk_id, chunk_state in dict(self.receive_chunks_in_progress).items():
            if chunk_state.send_id == send_id:
                self.cancel_file(chunk_id, message)
                return
        filelog.error(f"Error: cannot cancel download {send_id!r}, entry not found!")

    def cancel_file(self, chunk_id: str, message: str, chunk: int = 0) -> None:
        filelog("cancel_file%s", (chunk_id, message, chunk))
        chunk_state = self.receive_chunks_in_progress.get(chunk_id)
        if chunk_state:
            # mark it as cancelled:
            chunk_state.cancelled = True
            timer = chunk_state.timer
            if timer:
                chunk_state.timer = 0
                GLib.source_remove(timer)
            osclose(chunk_state.fd)

            # remove this transfer after a little while,
            # so in-flight packets won't cause errors

            def clean_receive_state() -> bool:
                self.receive_chunks_in_progress.pop(chunk_id, None)
                return False

            GLib.timeout_add(20000, clean_receive_state)
            filename = chunk_state.filename
            try:
                os.unlink(filename)
            except OSError as e:
                filelog(f"os.unlink({filename})", exc_info=True)
                filelog.error("Error: failed to delete temporary download file")
                filelog.error(f" {filename!r} : {e}")
        self.send("ack-file-chunk", chunk_id, False, message, chunk)

    def _process_send_file_chunk(self, packet: PacketType) -> None:
        chunk_id = str(packet[1])
        chunk = int(packet[2])
        file_data: SizedBuffer = packet[3]
        has_more = bool(packet[4])
        # if len(file_data)<1024:
        #    from xpra.util.str_fn import hexstr
        #    filelog.warn("file_data=%s", hexstr(file_data))
        # filelog(f"file_data={len(file_data)} {type(file_data)}")
        filelog(f"file_data={len(file_data)} {type(file_data)}")
        filelog("_process_send_file_chunk%s", (chunk_id, chunk, f"{len(file_data)} bytes", has_more))
        chunk_state = self.receive_chunks_in_progress.get(chunk_id)

        def progress(position: int, error="") -> None:
            s_elapsed = monotonic() - chunk_state.start
            self.transfer_progress_update(False, chunk_state.send_id, s_elapsed, position, chunk_state.filesize, error)

        def error(message: str) -> None:
            filelog.error(f"Error: {message}")
            self.cancel_file(chunk_id, message, chunk)
            if chunk_state:
                if chunk_state.fd:
                    osclose(chunk_state.fd)
                filename = chunk_state.filename
                if filename and os.path.exists(filename):
                    try:
                        os.unlink(filename)
                    except OSError:
                        filelog.error(f"Error: failed to delete uploaded file {filename!r}")
            progress(-1, message)

        if not chunk_state:
            error(f"file transfer id {chunk_id!r} not found")
            return

        if chunk_state.cancelled:
            filelog("got chunk for a cancelled file transfer, ignoring it")
            return

        fd = chunk_state.fd
        if chunk_state.chunk + 1 != chunk:
            error("chunk number mismatch")
            return

        # update chunk number:
        chunk_state.chunk = chunk
        try:
            os.write(fd, file_data)
            if chunk_state.digest:
                chunk_state.digest.update(file_data)
            chunk_state.written += len(file_data)
        except OSError as e:
            error(f"cannot write file chunk: {e}")
            return

        if chunk_state.written > chunk_state.filesize:
            error("more data received than specified in the file size!")
            return

        self.send("ack-file-chunk", chunk_id, True, "", chunk)
        if chunk_state.cancelled:
            # check again if the transfer has been cancelled
            filelog("got chunk for a cancelled file transfer, ignoring it")
            return

        if has_more:
            progress(chunk_state.written)
            if chunk_state.timer:
                GLib.source_remove(chunk_state.timer)
            # remote end will send more after receiving the ack
            chunk_state.timer = GLib.timeout_add(CHUNK_TIMEOUT, self._check_chunk_receiving, chunk_id, chunk)
            pct = round(100 * chunk_state.written / chunk_state.filesize)
            filelog(f"waiting for the next chunk, got {chunk_state.written:8} of {chunk_state.filesize:8}: {pct:3}%")
            return

        # we have received all the packets
        self.receive_chunks_in_progress.pop(chunk_id, None)
        osclose(fd)
        filename = chunk_state.filename
        options = chunk_state.options
        filelog(f"file {filename!r} complete")
        if chunk_state.digest:
            expected_digest = options.strget(chunk_state.digest.name)  # ie: "sha256"
            if expected_digest and chunk_state.digest.hexdigest() != expected_digest:
                digest_mismatch(filename, chunk_state.digest, expected_digest)
                error("checksum mismatch")
                return
            filelog("%s digest matches: %s", chunk_state.digest.name, expected_digest)

        # check file size and digest then process it:
        if chunk_state.written != chunk_state.filesize:
            error(f"expected a file of {chunk_state.filesize} bytes, got {chunk_state.written}")
            return

        progress(chunk_state.written)
        elapsed = monotonic() - chunk_state.start
        filelog("%i bytes received in %i chunks, took %ims", chunk_state.filesize, chunk, elapsed * 1000)
        self.process_downloaded_file(filename, chunk_state.mimetype,
                                     chunk_state.printit, chunk_state.openit, chunk_state.filesize, options)

    def accept_data(self, send_id: str, dtype, basefilename: str,
                    printit: bool, openit: bool) -> tuple[bool, bool, bool]:
        # subclasses should check the flags,
        # and if ask is True, verify they have accepted this specific send_id
        filelog("accept_data%s", (send_id, dtype, basefilename, printit, openit))
        filelog("accept_data: printing=%s, printing-ask=%s",
                self.printing, self.printing_ask)
        filelog("accept_data: file-transfer=%s, file-transfer-ask=%s",
                self.file_transfer, self.file_transfer_ask)
        filelog("accept_data: open-files=%s, open-files-ask=%s",
                self.open_files, self.open_files_ask)
        req = self.files_accepted.pop(send_id, None)
        filelog("accept_data: files_accepted[%s]=%s", send_id, req)
        if req is not None:
            return True, False, req
        if printit:
            if not self.printing or self.printing_ask:
                printit = False
        elif not self.file_transfer or self.file_transfer_ask:
            return False, False, False
        if openit and (not self.open_files or self.open_files_ask):
            # we can't ask in this implementation,
            # so deny the request to open it:
            openit = False
        return True, printit, openit

    def _process_send_file(self, packet: PacketType) -> None:
        # the remote end is sending us a file
        start = monotonic()
        basefilename = str(packet[1])
        mimetype = str(packet[2])
        printit = bool(packet[3])
        openit = bool(packet[4])
        filesize = int(packet[5])
        file_data: SizedBuffer = packet[6]
        options: typedict = typedict(packet[7])
        send_id = ""
        if len(packet) >= 9:
            send_id = str(packet[8])
        chunk_id = options.strget("file-chunk-id")

        def cancel(message: str) -> None:
            log.error(f"Error: {message}")
            if chunk_id:
                self.cancel_file(chunk_id, message, chunk)

        if filesize <= 0:
            cancel(f"invalid file size {filesize} for {basefilename!r}")
            return
        if filesize > self.file_size_limit:
            fstr = std_unit(filesize)
            limstr = std_unit(self.file_size_limit)
            cancel(f"file {basefilename!r} is too large: {fstr}B, the file size limit is {limstr}B")
            return

        args = (send_id, "file", basefilename, printit, openit)
        acceptit, printit, openit = self.accept_data(*args)
        filelog("%s%s=%s", self.accept_data, args, (acceptit, printit, openit))
        if not acceptit:
            ftype = "printing" if printit else "transfer"
            cancel(f"{ftype} rejected for file {basefilename!r}")
            return

        # accept_data() method can override the flags:
        if printit:
            log = printlog
            assert self.printing
        else:
            log = filelog
            assert self.file_transfer
        log("receiving file: %s",
            (basefilename, mimetype, printit, openit, filesize, f"{len(file_data)} bytes", options))

        try:
            filename, fd = safe_open_download_file(basefilename, mimetype)
        except OSError as e:
            log("cannot save file %s / %s", basefilename, mimetype, exc_info=True)
            cancel(f"failed to save downloaded file: {e}")
            return
        self.file_descriptors.add(fd)

        # from now on, call error() so we also close / cleanup the temporary file:
        def error(message: str) -> None:
            cancel(message)
            if fd:
                try:
                    os.close(fd)
                except OSError:
                    log.error(f"Error: failed to close {fd=} used for file transfer")
                else:
                    try:
                        self.file_descriptors.remove(fd)
                    except KeyError:
                        pass

        digest: hashlib._Hash | None = None
        for hash_fn in ("sha512", "sha384", "sha256", "sha224", "sha1"):
            if options.strget(hash_fn):
                digest = getattr(hashlib, hash_fn)()
                break
        if chunk_id:
            chunk = 0
            nfiles = len(self.receive_chunks_in_progress)
            if nfiles >= MAX_CONCURRENT_FILES:
                error(f"too many file transfers in progress: {nfiles}")
                return
            timer = GLib.timeout_add(CHUNK_TIMEOUT, self._check_chunk_receiving, chunk_id, chunk)
            self.receive_chunks_in_progress[chunk_id] = ReceiveChunkState(monotonic(),
                                                                          fd, filename, mimetype,
                                                                          printit, openit, filesize,
                                                                          options, digest, 0, False, send_id,
                                                                          timer, chunk)
            self.send("ack-file-chunk", chunk_id, True, b"", chunk)
            return
        # not chunked, full file:
        if not file_data:
            error("no file data")
            return
        if len(file_data) != filesize:
            error(f"file {basefilename!r} size: received {len(file_data)} bytes, expected {filesize} bytes")
            return
        # check digest if present:
        if digest:
            digest.update(file_data)
            expected_digest = options.strget(digest.name)  # ie: "sha256"
            if expected_digest and digest.hexdigest() != expected_digest:
                digest_mismatch(basefilename, digest, expected_digest)
                error("checksum mismatch")
                return
            log("%s digest matches: %s", digest.name, expected_digest)
        try:
            os.write(fd, file_data)
        except OSError as e:
            error(f"failed to write file data: {e}")
            return
        finally:
            osclose(fd)
        self.transfer_progress_update(False, send_id, monotonic() - start, filesize, filesize, None)
        self.process_downloaded_file(filename, mimetype, printit, openit, filesize, options)

    def process_downloaded_file(self, filename: str, mimetype: str,
                                printit: bool, openit: bool, filesize: int, options) -> None:
        sizestr = std_unit(filesize)
        ftype = mimetype or "temporary"
        extra = " for printing" if printit else ""
        filelog.info(f"downloaded {sizestr} bytes to {ftype} file{extra}:")
        filelog.info(f" {filename!r}")
        # some file requests may have a custom callback
        # (ie: bug report tool will just include the file)
        rf = options.tupleget("request-file")
        if rf and len(rf) >= 2:
            argf = rf[0]
            cb = self.file_request_callback.pop(argf, None)
            if cb:
                cb(filename, filesize)
                return
        if printit or openit:
            t = start_thread(self.do_process_downloaded_file, "process-download", daemon=False,
                             args=(filename, mimetype, printit, openit, filesize, options))
            filelog("started process-download thread: %s", t)

    def do_process_downloaded_file(self, filename: str, mimetype: str, printit: bool, openit: bool, filesize: int,
                                   options: typedict) -> None:
        filelog("do_process_downloaded_file%s", (filename, mimetype, printit, openit, filesize, options))
        if printit:
            self._print_file(filename, mimetype, options)
            return
        if openit:
            if not self.open_files:
                filelog.warn("Warning: opening files automatically is disabled,")
                filelog.warn(" ignoring uploaded file:")
                filelog.warn(" '%s'", filename)
                return
            self._open_file(filename)

    def _print_file(self, filename: str, mimetype: str, options: typedict) -> None:
        printlog("print_file%s", (filename, mimetype, options))
        printer = options.strget("printer")
        title = options.strget("title")
        copies = options.intget("copies", 1)
        if title:
            printlog.info(" sending '%s' to printer '%s'", title, printer)
        else:
            printlog.info(" sending to printer '%s'", printer)
        from xpra.platform.printing import print_files, printing_finished, get_printers
        printers = get_printers()

        def delfile() -> None:
            if DELETE_PRINTER_FILE:
                try:
                    os.unlink(filename)
                except OSError:
                    printlog("failed to delete print job file '%s'", filename)

        if not printer:
            printlog.error("Error: the printer name is missing")
            printlog.error(" printers available: %s", csv(printers.keys()) or "none")
            delfile()
            return
        if printer not in printers:
            printlog.error(f"Error: printer {printer!r} does not exist!")
            printlog.error(" printers available: %s", csv(printers.keys()) or "none")
            delfile()
            return
        try:
            job_options = options.dictget("options", {})
            job_options["copies"] = copies
            job = print_files(printer, [filename], title, job_options)
        except Exception as e:
            printlog("print_files%s", (printer, [filename], title, options), exc_info=True)
            printlog.error("Error: cannot print file '%s'", os.path.basename(filename))
            printlog.estr(e)
            delfile()
            return
        printlog(f"printing {filename!r}, job={job}")
        if job <= 0:
            printlog(f"printing failed and returned {job}")
            delfile()
            return
        start = monotonic()

        def check_printing_finished() -> bool:
            done = printing_finished(job)
            printlog("printing_finished(%s)=%s", job, done)
            if done:
                delfile()
                return False
            if monotonic() - start >= PRINT_JOB_TIMEOUT:
                printlog.warn("Warning: print job %s timed out", job)
                delfile()
                return False
            return True  # try again..

        if check_printing_finished():
            # check every 10 seconds:
            GLib.timeout_add(10000, check_printing_finished)

    def _open_file(self, url: str) -> None:
        filelog("_open_file(%s)", url)
        self.exec_open_command(url)

    def _open_url(self, url: str) -> None:
        filelog("_open_url(%s)", url)
        if POSIX:
            # we can't use webbrowser,
            # because this will use "xdg-open" from the $PATH
            # which may point back to us!
            self.exec_open_command(url)
        else:
            import webbrowser  # pylint: disable=import-outside-toplevel
            webbrowser.open_new_tab(url)

    def exec_open_command(self, url: str) -> None:
        filelog("exec_open_command(%s)", url)
        try:
            import shlex  # pylint: disable=import-outside-toplevel
            command = shlex.split(self.open_command) + [url]
        except ImportError as e:
            filelog("exec_open_command(%s) no shlex: %s", url, e)
            command = self.open_command.split(" ")
        filelog("exec_open_command(%s) command=%s", url, command)
        try:
            # pylint: disable=consider-using-with
            proc = subprocess.Popen(command, env=get_open_env(), shell=WIN32)
        except Exception as e:
            filelog("exec_open_command(%s)", url, exc_info=True)
            filelog.error("Error: cannot open '%s': %s", url, e)
            return
        filelog("exec_open_command(%s) Popen(%s)=%s", url, command, proc)

        def open_done(*_args) -> None:
            returncode = proc.poll()
            filelog("open_file: command %s has ended, returncode=%s", command, returncode)
            if returncode != 0:
                filelog.warn("Warning: failed to open the downloaded content")
                filelog.warn(" '%s' returned %s", " ".join(command), returncode)

        cr = getChildReaper()
        cr.add_process(proc, f"Open file {url}", command, True, True, open_done)

    def file_size_warning(self, action: str, location: str, basefilename: str, filesize: int, limit: int) -> None:
        filelog.warn("Warning: cannot %s the file '%s'", action, basefilename)
        filelog.warn(" this file is too large: %sB", std_unit(filesize))
        filelog.warn(" the %s file size limit is %sB", location, std_unit(limit))

    def check_file_size(self, action: str, filename: str, filesize: int) -> bool:
        basefilename = os.path.basename(filename)
        if filesize > self.file_size_limit:
            self.file_size_warning(action, "local", basefilename, filesize, self.file_size_limit)
            return False
        if filesize > self.remote_file_size_limit:
            self.file_size_warning(action, "remote", basefilename, filesize, self.remote_file_size_limit)
            return False
        return True

    def send_request_file(self, filename: str, openit: bool = True):
        self.send("request-file", filename, openit)
        self.files_requested[filename] = openit

    def _process_open_url(self, packet: PacketType) -> None:
        send_id = str(packet[2])
        url = str(packet[1])
        if not self.open_url:
            filelog.warn("Warning: received a request to open URL '%s'", url)
            filelog.warn(" but opening of URLs is disabled")
            return
        if self.open_url_ask:
            acceptit, _printit, _openit = self.accept_data(send_id, "url", url, False, True)
            if not acceptit:
                filelog("url '%s' not accepted", url)
                return
        self._open_url(url)

    def send_open_url(self, url: str) -> bool:
        if not self.remote_open_url:
            filelog.warn("Warning: remote end does not accept URLs")
            return False
        if self.remote_open_url_ask:
            # ask the client if it is OK to send
            return bool(self.send_data_request("open", "url", url))
        self.do_send_open_url(url)
        return True

    def do_send_open_url(self, url: str, send_id: str = "") -> None:
        self.send("open-url", url, send_id)

    def send_file(self, filename: str, mimetype: str, data: SizedBuffer, filesize=0,
                  printit=False, openit=False, options=None) -> bool:
        if printit:
            if not self.printing:
                printlog.warn("Warning: printing is not enabled for %s", self)
                return False
            if not self.remote_printing:
                printlog.warn("Warning: remote end does not support printing")
                return False
            logger = printlog
            ask = self.remote_printing_ask
            action = "print"
        else:
            if not self.file_transfer:
                filelog.warn("Warning: file transfers are not enabled for %s", self)
                return False
            if not self.remote_file_transfer:
                filelog.warn("Warning: remote end does not support file transfers")
                return False
            logger = filelog
            ask = self.remote_file_transfer_ask
            action = "upload"
            if openit:
                if not self.remote_open_files:
                    logger.info("opening the file after transfer is disabled on the remote end")
                    logger.info(" sending only, the file will need to be opened manually")
                    openit = False
                    action = "upload"
                else:
                    ask |= self.remote_open_files_ask
                    action = "open"
        assert len(data) >= filesize, "data is smaller then the given file size!"
        data = data[:filesize]  # gio may null terminate it
        logger("send_file%s action=%s, ask=%s",
               (filename, mimetype, type(data), f"{filesize} bytes", printit, openit, options), action, ask)
        self.dump_remote_caps()
        if not self.check_file_size(action, filename, filesize):
            return False
        if ask:
            return bool(self.send_data_request(action, "file", filename, mimetype, data, filesize,
                                               printit, openit, options))
        send_id = uuid.uuid4().hex
        self.do_send_file(filename, mimetype, data, filesize, printit, openit, options, send_id)
        return True

    def send_data_request(self, action: str, dtype: str, url: str, mimetype="", data=b"", filesize=0,
                          printit=False, openit=True, options=None) -> str:
        send_id = uuid.uuid4().hex
        if len(self.pending_send_data) >= MAX_CONCURRENT_FILES:
            filelog.warn("Warning: %s dropped", action)
            filelog.warn(" %i transfers already waiting for a response", len(self.pending_send_data))
            return ""
        spd = SendPendingData(dtype, url, mimetype, data, filesize, printit, openit, options or {})
        self.pending_send_data[send_id] = spd
        delay = self.remote_file_ask_timeout * 1000
        self.pending_send_data_timers[send_id] = GLib.timeout_add(delay, self.send_data_ask_timeout, send_id)
        filelog(f"sending data request for {dtype} {url!r} with send-id {send_id!r}")
        self.send("send-data-request", dtype, send_id, url, mimetype, filesize, printit, openit, options or {})
        return send_id

    def _process_send_data_request(self, packet: PacketType) -> None:
        dtype, send_id, url, _, filesize, printit, openit = packet[1:8]
        options = {}
        if len(packet) >= 9:
            options = packet[8]
        # filenames and url are always sent encoded as utf8:
        self.do_process_send_data_request(dtype, send_id, url, _, filesize, printit, openit, typedict(options))

    def do_process_send_data_request(self, dtype: str, send_id: str, url: str, _, filesize: int,
                                     printit: bool, openit: bool, options: typedict) -> None:
        filelog(f"do_process_send_data_request: {send_id=}, {url=}, {printit=}, {openit=}, {options=}")

        def cb_answer(accept: bool) -> None:
            filelog("accept%s=%s", (url, printit, openit), accept)
            self.send("send-data-response", send_id, accept)

        # could be a request we made:
        # (in which case we can just accept it without prompt)
        rf = options.tupleget("request-file")
        if rf and len(rf) >= 2:
            argf, openit = rf[:2]
            openit = self.files_requested.pop(argf, None)
            if openit is not None:
                self.files_accepted[send_id] = openit
                cb_answer(True)
                return
        if dtype == "file":
            if not self.file_transfer:
                cb_answer(False)
                return
            url = os.path.basename(url)
            if printit:
                ask = self.printing_ask
            elif openit:
                ask = self.file_transfer_ask or self.open_files_ask
            else:
                ask = self.file_transfer_ask
        elif dtype == "url":
            if not self.open_url:
                cb_answer(False)
                return
            ask = self.open_url_ask
        else:
            filelog.warn("Warning: unknown data request type '%s'", dtype)
            cb_answer(False)
            return
        if not ask:
            filelog.warn("Warning: received a send-data request for a %s,", dtype)
            filelog.warn(" but authorization is not required by the client")
            # fail it because if we responded with True,
            # it would fail later when we don't find this send_id in our accepted list
            cb_answer(False)
            return
        self.ask_data_request(cb_answer, send_id, dtype, url, filesize, printit, openit)

    def ask_data_request(self, cb_answer: Callable[[bool], None],
                         send_id: str, dtype: str, url: str, filesize: int,
                         printit: bool, openit: bool) -> None:
        # subclasses may prompt the user here instead
        filelog("ask_data_request%s", (send_id, dtype, url, filesize, printit, openit))
        v = self.accept_data(send_id, dtype, url, printit, openit)
        cb_answer(v[0])

    def _process_send_data_response(self, packet: PacketType) -> None:
        send_id = str(packet[1])
        accept = int(packet[2])
        filelog("process send-data-response: send_id=%s, accept=%s", send_id, accept)
        timer = self.pending_send_data_timers.pop(send_id, None)
        if timer:
            GLib.source_remove(timer)
        try:
            spd: SendPendingData = self.pending_send_data[send_id]
        except KeyError:
            filelog.warn(f"Warning: cannot find send-file entry for {send_id!r}")
            return
        if accept == DENY:
            filelog.info("the request to send %s '%s' has been denied", spd.datatype, spd.url)
            return
        if accept not in (ACCEPT, OPEN):
            raise ValueError(f"unknown value for send-data response: {accept!r}")
        if spd.datatype == "file":
            if accept == ACCEPT:
                self.do_send_file(spd.url, spd.mimetype, spd.data, spd.filesize,
                                  spd.printit, spd.openit, spd.options, send_id)
            else:
                assert spd.openit and accept == OPEN
                # try to open at this end:
                self._open_file(spd.url)
        elif spd.datatype == "url":
            if accept == ACCEPT:
                self.do_send_open_url(spd.url, send_id)
            else:
                assert accept == OPEN
                # open it at this end:
                self._open_url(spd.url)
        else:
            filelog.error("Error: unknown datatype '%s'", spd.datatype)

    def send_data_ask_timeout(self, send_id: str) -> bool:
        self.pending_send_data_timers.pop(send_id, None)
        spd = self.pending_send_data.pop(send_id, None)
        if not spd:
            filelog.warn(f"Warning: send timeout, id {send_id!r} not found!")
            return False
        filelog.warn("Warning: failed to %s file '%s',", ["send", "print"][spd.printit], spd.url)
        filelog.warn(" the send approval request timed out")
        return False

    def do_send_file(self, filename: str, mimetype: str, data, filesize: int = 0,
                     printit: bool = False, openit: bool = False, options=None, send_id: str = "") -> bool:
        if printit:
            action = "print"
            logger = printlog
        else:
            action = "upload"
            logger = filelog
        logger("do_send_file%s", (filename, mimetype, type(data), f"{filesize} bytes", printit, openit, options))
        if not self.check_file_size(action, filename, filesize):
            return False
        h = hashlib.sha256()
        h.update(data)
        absfile = os.path.abspath(filename)
        filelog(f"sha256 digest({absfile})=%s", h.hexdigest())
        options = options or {}
        options["sha256"] = h.hexdigest()
        chunk_size = min(self.file_chunks, self.remote_file_chunks)
        if 0 < chunk_size < filesize:
            in_progress = len(self.send_chunks_in_progress)
            if in_progress >= MAX_CONCURRENT_FILES:
                raise RuntimeError(f"too many file transfers in progress: {in_progress}")
            # chunking is supported and the file is big enough
            chunk_id = uuid.uuid4().hex
            options["file-chunk-id"] = chunk_id
            # timer to check that the other end is requesting more chunks:
            chunk_no = 0
            timer = GLib.timeout_add(CHUNK_TIMEOUT, self._check_chunk_sending, chunk_id, chunk_no)
            self.send_chunks_in_progress[chunk_id] = SendChunkState(monotonic(), data, chunk_size, timer, chunk_no)
            cdata = b""
            filelog("using chunks, sending initial file-chunk-id=%s, for chunk size=%s",
                    chunk_id, chunk_size)
        else:
            # send everything now:
            cdata = self.compressed_wrapper("file-data", data)
            assert len(cdata) <= filesize  # compressed wrapper ensures this is true
            filelog("sending full file: %i bytes (chunk size=%i)", filesize, chunk_size)
        basefilename = os.path.basename(filename)
        self.send("send-file", basefilename, mimetype, printit, openit, filesize, cdata, options, send_id)
        return True

    def _check_chunk_sending(self, chunk_id: str, chunk_no: int) -> None:
        chunk_state = self.send_chunks_in_progress.get(chunk_id)
        filelog("_check_chunk_sending(%s, %s) chunk_state found: %s", chunk_id, chunk_no, bool(chunk_state))
        if not chunk_state:
            # transfer already removed
            return
        chunk_state.timer = 0  # timer has fired
        if chunk_state.chunk == chunk_no:
            filelog.error(f"Error: chunked file transfer {chunk_id} timed out")
            filelog.error(f" on chunk {chunk_no}")
            self.cancel_sending(chunk_id)

    def cancel_sending(self, chunk_id: str) -> None:
        chunk_state = self.send_chunks_in_progress.pop(chunk_id, None)
        filelog("cancel_sending(%s) chunk state found: %s", chunk_id, bool(chunk_state))
        if not chunk_state:
            return
        timer = chunk_state.timer
        if timer:
            chunk_state.timer = 0
            GLib.source_remove(timer)

    def _process_ack_file_chunk(self, packet: PacketType) -> None:
        # the other end received our send-file or send-file-chunk,
        # send some more file data
        filelog("ack-file-chunk: %s", packet[1:])
        chunk_id = str(packet[1])
        state = bool(packet[2])
        error_message = str(packet[3])
        chunk = int(packet[4])
        if not state:
            filelog.info("the remote end is cancelling the file transfer:")
            filelog.info(" %s", error_message)
            self.cancel_sending(chunk_id)
            return
        chunk_state = self.send_chunks_in_progress.get(chunk_id)
        if not chunk_state:
            filelog.error(f"Error: cannot find the file transfer id {chunk_id!r}")
            return
        if chunk_state.chunk != chunk:
            filelog.error("Error: chunk number mismatch (%i vs %i)", chunk_state.chunk, chunk)
            self.cancel_sending(chunk_id)
            return
        chunk_size = chunk_state.chunk_size
        if not chunk_state.data:
            # all sent!
            elapsed = monotonic() - chunk_state.start
            if elapsed > 0:
                bs = chunk * chunk_size / elapsed
            else:
                bs = 9999 * 1000 * 1000
            filelog("%i chunks of %i bytes sent in %ims (%sB/s)",
                    chunk, chunk_size, elapsed * 1000, std_unit(bs))
            self.cancel_sending(chunk_id)
            return
        assert chunk_size > 0
        # carve out another chunk:
        cdata = self.compressed_wrapper("file-data", chunk_state.data[:chunk_size])
        chunk_state.data = chunk_state.data[chunk_size:]
        chunk += 1
        chunk_state.chunk = chunk
        if chunk_state.timer:
            GLib.source_remove(chunk_state.timer)
        chunk_state.timer = GLib.timeout_add(CHUNK_TIMEOUT, self._check_chunk_sending, chunk_id, chunk)
        self.send("send-file-chunk", chunk_id, chunk, cdata, bool(chunk_state.data))

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        raise NotImplementedError()

    def compressed_wrapper(self, datatype, data, level=5):
        raise NotImplementedError()

    def transfer_progress_update(self, send=True, transfer_id: str = "", elapsed=0.0, position=0, total=0,
                                 error=None) -> None:
        # this method is overridden in the gtk client:
        filelog("transfer_progress_update%s", (send, transfer_id, elapsed, position, total, error))
