# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess, shlex
import hashlib
import uuid

from xpra.log import Logger
printlog = Logger("printing")
filelog = Logger("file")

from xpra.child_reaper import getChildReaper
from xpra.os_util import monotonic_time, bytestostr, strtobytes, POSIX
from xpra.util import typedict, csv, nonl, envint, envbool, engs
from xpra.scripts.config import parse_bool
from xpra.simple_stats import std_unit
from xpra.make_thread import start_thread

DELETE_PRINTER_FILE = envbool("XPRA_DELETE_PRINTER_FILE", True)
FILE_CHUNKS_SIZE = max(0, envint("XPRA_FILE_CHUNKS_SIZE", 65536))
MAX_CONCURRENT_FILES = max(1, envint("XPRA_MAX_CONCURRENT_FILES", 10))
PRINT_JOB_TIMEOUT = max(60, envint("XPRA_PRINT_JOB_TIMEOUT", 3600))
SEND_REQUEST_TIMEOUT = max(300, envint("XPRA_SEND_REQUEST_TIMEOUT", 3600))
CHUNK_TIMEOUT = 10*1000

MIMETYPE_EXTS = {
                 "application/postscript"   : "ps",
                 "application/pdf"          : "pdf",
                 "raw"                      : "raw",
                 }

DENY = 0
ACCEPT = 1
OPEN = 2


def safe_open_download_file(basefilename, mimetype):
    from xpra.platform.paths import get_download_dir
    #make sure we use a filename that does not exist already:
    dd = os.path.expanduser(get_download_dir())
    base = os.path.basename(basefilename)
    wanted_filename = os.path.abspath(os.path.join(dd, base))
    ext = MIMETYPE_EXTS.get(mimetype)
    if ext:
        #on some platforms (win32),
        #we want to force an extension
        #so that the file manager can display them properly when you double-click on them
        if not wanted_filename.endswith("."+ext):
            wanted_filename += "."+ext
    filename = wanted_filename
    base = 0
    while os.path.exists(filename):
        filelog("cannot save file as %s: file already exists", filename)
        root, ext = os.path.splitext(wanted_filename)
        base += 1
        filename = root+("-%s" % base)+ext
    flags = os.O_CREAT | os.O_RDWR | os.O_EXCL
    try:
        flags |= os.O_BINARY                #@UndefinedVariable (win32 only)
    except:
        pass
    fd = os.open(filename, flags)
    filelog("using filename '%s'", filename)
    return filename, fd


class FileTransferAttributes(object):
    def __init__(self, attrs=None):
        self.init_attributes()
        if attrs:
            #copy attributes
            for x in ("file_transfer", "file_transfer_ask", "file_size_limit", "file_chunks",
                      "printing", "printing_ask", "open_files", "open_files_ask",
                      "open_url", "open_url_ask",
                      "file_ask_timeout", "open_command"):
                setattr(self, x, getattr(attrs, x))

    def init_opts(self, opts):
        #get the settings from a config object
        self.init_attributes(opts.file_transfer, opts.file_size_limit, opts.printing, opts.open_files, opts.open_url, opts.open_command)

    def init_attributes(self, file_transfer="yes", file_size_limit=10, printing="yes", open_files="no", open_url="yes", open_command=None):
        filelog("file transfer: init_attributes%s", (file_transfer, file_size_limit, printing, open_files, open_url, open_command))
        #printing and file transfer:
        self.file_transfer_ask = file_transfer.lower() in ("ask", "auto")
        self.file_transfer = self.file_transfer_ask or parse_bool("file-transfer", file_transfer)
        self.file_size_limit = file_size_limit
        self.file_chunks = min(self.file_size_limit*1024*1024, FILE_CHUNKS_SIZE)
        self.printing_ask = printing.lower() in ("ask", "auto")
        self.printing = self.printing_ask or parse_bool("printing", printing)
        self.open_files_ask = open_files.lower() in ("ask", "auto")
        self.open_files = self.open_files_ask or parse_bool("open-files", open_files)
        #FIXME: command line options needed here:
        self.open_url_ask = open_url.lower() in ("ask", "auto")
        self.open_url = self.open_url_ask or parse_bool("open-url", open_url)
        self.file_ask_timeout = SEND_REQUEST_TIMEOUT
        self.open_command = open_command
        filelog("file transfer attributes=%s", self.get_file_transfer_features())

    def get_file_transfer_features(self):
        #used in hello packets
        return {
                "file-transfer"     : self.file_transfer,
                "file-transfer-ask" : self.file_transfer_ask,
                "file-size-limit"   : self.file_size_limit,
                "file-chunks"       : self.file_chunks,
                "open-files"        : self.open_files,
                "open-files-ask"    : self.open_files_ask,
                "printing"          : self.printing,
                "printing-ask"      : self.printing_ask,
                "open-url"          : self.open_url,
                "open-url-ask"      : self.open_url_ask,
                "file-ask-timeout"  : self.file_ask_timeout,
                }

    def get_info(self):
        #slightly different from above... for legacy reasons
        #this one is used for get_info() in a proper "file." namespace from server_base.py
        return {
                "enabled"           : self.file_transfer,
                "ask"               : self.file_transfer_ask,
                "size-limit"        : self.file_size_limit,
                "chunks"            : self.file_chunks,
                "open"              : self.open_files,
                "open-ask"          : self.open_files_ask,
                "open-url"          : self.open_url,
                "open-url-ask"      : self.open_url_ask,
                "printing"          : self.printing,
                "printing-ask"      : self.printing_ask,
                "ask-timeout"       : self.file_ask_timeout,
                }


class FileTransferHandler(FileTransferAttributes):
    """
        Utility class for receiving files and optionally printing them,
        used by both clients and server to share the common code and attributes
    """

    def init_attributes(self, *args):
        FileTransferAttributes.init_attributes(self, *args)
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
        self.pending_send_data = {}
        self.pending_send_data_timers = {}
        self.send_chunks_in_progress = {}
        self.receive_chunks_in_progress = {}
        self.file_descriptors = set()
        if not getattr(self, "timeout_add", None):
            from xpra.gtk_common.gobject_compat import import_glib
            glib = import_glib()
            self.timeout_add = glib.timeout_add
            self.idle_add = glib.idle_add
            self.source_remove = glib.source_remove

    def cleanup(self):
        for t in self.pending_send_data_timers.values():
            self.source_remove(t)
        self.pending_send_data_timers = {}
        for v in self.receive_chunks_in_progress.values():
            t = v[-2]
            self.source_remove(t)
        self.receive_chunks_in_progress = {}
        for x in tuple(self.file_descriptors):
            try:
                x.close()
            except:
                pass
        self.file_descriptors = set()
        self.init_attributes()

    def parse_file_transfer_caps(self, c):
        self.remote_file_transfer = c.boolget("file-transfer")
        self.remote_file_transfer_ask = c.boolget("file-transfer-ask")
        self.remote_printing = c.boolget("printing")
        self.remote_printing_ask = c.boolget("printing-ask")
        self.remote_open_files = c.boolget("open-files")
        self.remote_open_files_ask = c.boolget("open-files-ask")
        self.remote_open_url = c.boolget("open-url")
        self.remote_open_url_ask = c.boolget("open-url-ask")
        self.remote_file_ask_timeout = c.intget("file-ask-timeout")
        self.remote_file_size_limit = c.intget("file-size-limit")
        self.remote_file_chunks = max(0, min(self.remote_file_size_limit*1024*1024, c.intget("file-chunks")))
        self.dump_remote_caps()

    def dump_remote_caps(self):
        filelog("file transfer remote caps: file-transfer=%s   (ask=%s)", self.remote_file_transfer, self.remote_file_transfer_ask)
        filelog("file transfer remote caps: printing=%s        (ask=%s)", self.remote_printing, self.remote_printing_ask)
        filelog("file transfer remote caps: open-files=%s      (ask=%s)", self.remote_open_files, self.remote_open_files_ask)
        filelog("file transfer remote caps: open-url=%s        (ask=%s)", self.remote_open_url, self.remote_open_url_ask)

    def get_info(self):
        info = FileTransferAttributes.get_info(self)
        info["remote"] = {
                          "file-transfer"   : self.remote_file_transfer,
                          "file-transfer-ask" : self.remote_file_transfer_ask,
                          "file-size-limit" : self.remote_file_size_limit,
                          "file-chunks"     : self.remote_file_chunks,
                          "open-files"      : self.remote_open_files,
                          "open-files-ask"  : self.remote_open_files_ask,
                          "open-url"        : self.remote_open_url,
                          "open-url-ask"    : self.remote_open_url_ask,
                          "printing"        : self.remote_printing,
                          "printing-ask"    : self.remote_printing_ask,
                          "file-ask-timeout" : self.remote_file_ask_timeout,
                          }
        return info

    def check_digest(self, filename, digest, expected_digest, algo="sha1"):
        if digest!=expected_digest:
            filelog.error("Error: data does not match, invalid %s file digest for '%s'", algo, filename)
            filelog.error(" received %s, expected %s", digest, expected_digest)
            raise Exception("failed %s digest verification" % algo)
        else:
            filelog("%s digest matches: %s", algo, digest)


    def _check_chunk_receiving(self, chunk_id, chunk_no):
        chunk_state = self.receive_chunks_in_progress.get(chunk_id)
        filelog("_check_chunk_receiving(%s, %s) chunk_state=%s", chunk_id, chunk_no, chunk_state)
        if chunk_state:
            chunk_state[-2] = 0     #this timer has been used
            if chunk_state[-1]==0:
                filelog.error("Error: chunked file transfer timed out")
                del self.receive_chunks_in_progress[chunk_id]

    def _process_send_file_chunk(self, packet):
        chunk_id, chunk, file_data, has_more = packet[1:5]
        filelog("_process_send_file_chunk%s", (chunk_id, chunk, "%i bytes" % len(file_data), has_more))
        chunk_state = self.receive_chunks_in_progress.get(chunk_id)
        if not chunk_state:
            filelog.error("Error: cannot find the file transfer id '%s'", nonl(bytestostr(chunk_id)))
            self.send("ack-file-chunk", chunk_id, False, "file transfer id not found", chunk)
            return
        fd = chunk_state[1]
        if chunk_state[-1]+1!=chunk:
            filelog.error("Error: chunk number mismatch, expected %i but got %i", chunk_state[-1]+1, chunk)
            self.send("ack-file-chunk", chunk_id, False, "chunk number mismatch", chunk)
            del self.receive_chunks_in_progress[chunk_id]
            os.close(fd)
            return
        #update chunk number:
        chunk_state[-1] = chunk
        digest = chunk_state[8]
        written = chunk_state[9]
        try:
            os.write(fd, file_data)
            digest.update(file_data)
            written += len(file_data)
            chunk_state[9] = written
        except OSError as e:
            filelog.error("Error: cannot write file chunk")
            filelog.error(" %s", e)
            self.send("ack-file-chunk", chunk_id, False, "write error: %s" % e, chunk)
            del self.receive_chunks_in_progress[chunk_id]
            try:
                os.close(fd)
            except:
                pass
            return
        self.send("ack-file-chunk", chunk_id, True, "", chunk)
        if has_more:
            timer = chunk_state[-2]
            if timer:
                self.source_remove(timer)
            #remote end will send more after receiving the ack
            timer = self.timeout_add(CHUNK_TIMEOUT, self._check_chunk_receiving, chunk_id, chunk)
            chunk_state[-2] = timer
            return
        del self.receive_chunks_in_progress[chunk_id]
        os.close(fd)
        #check file size and digest then process it:
        filename, mimetype, printit, openit, filesize, options = chunk_state[2:8]
        if written!=filesize:
            filelog.error("Error: expected a file of %i bytes, got %i", filesize, written)
            return
        expected_digest = options.get("sha1")
        if expected_digest:
            self.check_digest(filename, digest.hexdigest(), expected_digest)
        start_time = chunk_state[0]
        elapsed = monotonic_time()-start_time
        filelog("%i bytes received in %i chunks, took %ims", filesize, chunk, elapsed*1000)
        t = start_thread(self.do_process_downloaded_file, "process-download", daemon=False, args=(filename, mimetype, printit, openit, filesize, options))
        filelog("started process-download thread: %s", t)

    def accept_data(self, _send_id, _dtype, _basefilename, printit, openit):
        #subclasses should check the flags,
        #and if ask is True, verify they have accepted this specific send_id
        if printit:
            return self.printing and not self.printing_ask
        if not self.file_transfer or self.file_transfer_ask:
            return False
        if openit:
            return self.open_files and not self.open_files_ask
        return True

    def _process_send_file(self, packet):
        #the remote end is sending us a file
        basefilename, mimetype, printit, openit, filesize, file_data, options = packet[1:8]
        send_id = ""
        if len(packet)>=9:
            send_id = packet[8]
        if not self.accept_data(send_id, b"file", basefilename, printit, openit):
            filelog.warn("Warning: file transfer rejected for file '%s'", bytestostr(basefilename))
            return
        options = typedict(options)
        if printit:
            l = printlog
            assert self.printing
        else:
            l = filelog
            assert self.file_transfer
        l("receiving file: %s", [basefilename, mimetype, printit, openit, filesize, "%s bytes" % len(file_data), options])
        assert filesize>0, "invalid file size: %s" % filesize
        if filesize>self.file_size_limit*1024*1024:
            l.error("Error: file '%s' is too large:", basefilename)
            l.error(" %iMB, the file size limit is %iMB", filesize//1024//1024, self.file_size_limit)
            return
        #basefilename should be utf8:
        try:
            base = basefilename.decode("utf8")
        except:
            base = bytestostr(basefilename)
        filename, fd = safe_open_download_file(base, mimetype)
        self.file_descriptors.add(fd)
        chunk_id = options.strget("file-chunk-id")
        if chunk_id:
            chunk_id = strtobytes(chunk_id)
            if len(self.receive_chunks_in_progress)>=MAX_CONCURRENT_FILES:
                self.send("ack-file-chunk", chunk_id, False, "too many file transfers in progress", 0)
                os.close(fd)
                return
            digest = hashlib.sha1()
            chunk = 0
            timer = self.timeout_add(CHUNK_TIMEOUT, self._check_chunk_receiving, chunk_id, chunk)
            chunk_state = [monotonic_time(), fd, filename, mimetype, printit, openit, filesize, options, digest, 0, timer, chunk]
            self.receive_chunks_in_progress[chunk_id] = chunk_state
            self.send("ack-file-chunk", chunk_id, True, "", chunk)
            return
        #not chunked, full file:
        assert file_data, "no data, got %s" % (file_data,)
        if len(file_data)!=filesize:
            l.error("Error: invalid data size for file '%s'", basefilename)
            l.error(" received %i bytes, expected %i bytes", len(file_data), filesize)
            return
        #check digest if present:
        def check_digest(algo="sha1", libfn=hashlib.sha1):
            digest = options.get(algo)
            if digest:
                u = libfn()
                u.update(file_data)
                l("%s digest: %s - expected: %s", algo, u.hexdigest(), digest)
                self.check_digest(basefilename, u.hexdigest(), digest, algo)
        check_digest("sha1", hashlib.sha1)
        check_digest("md5", hashlib.md5)
        try:
            os.write(fd, file_data)
        finally:
            os.close(fd)
        self.do_process_downloaded_file(filename, mimetype, printit, openit, filesize, options)

    def do_process_downloaded_file(self, filename, mimetype, printit, openit, filesize, options):
        filelog.info("downloaded %s bytes to %s file%s:", filesize, (mimetype or "temporary"), ["", " for printing"][int(printit)])
        filelog.info(" '%s'", filename)
        if printit:
            self._print_file(filename, mimetype, options)
            return
        elif openit:
            if not self.open_files:
                filelog.warn("Warning: opening files automatically is disabled,")
                filelog.warn(" ignoring uploaded file:")
                filelog.warn(" '%s'", filename)
                return
            self._open_file(filename)

    def _print_file(self, filename, mimetype, options):
        printlog("print_file%s", (filename, mimetype, options))
        printer = options.strget("printer")
        title   = options.strget("title")
        copies  = options.intget("copies", 1)
        if title:
            printlog.info(" sending '%s' to printer '%s'", title, printer)
        else:
            printlog.info(" sending to printer '%s'", printer)
        from xpra.platform.printing import print_files, printing_finished, get_printers
        printers = get_printers()
        def delfile():
            if not DELETE_PRINTER_FILE:
                return
            try:
                os.unlink(filename)
            except:
                printlog("failed to delete print job file '%s'", filename)
            return False
        if not printer:
            printlog.error("Error: the printer name is missing")
            printlog.error(" printers available: %s", csv(printers.keys()) or "none")
            delfile()
            return
        if printer not in printers:
            printlog.error("Error: printer '%s' does not exist!", printer)
            printlog.error(" printers available: %s", csv(printers.keys()) or "none")
            delfile()
            return
        try:
            job_options = options.get("options")
            job_options["copies"] = copies
            job = print_files(printer, [filename], title, job_options)
        except Exception as e:
            printlog("print_files%s", (printer, [filename], title, options), exc_info=True)
            printlog.error("Error: cannot print file '%s'", os.path.basename(filename))
            printlog.error(" %s", e)
            delfile()
            return
        printlog("printing %s, job=%s", filename, job)
        if job<=0:
            printlog("printing failed and returned %i", job)
            delfile()
            return
        start = monotonic_time()
        def check_printing_finished():
            done = printing_finished(job)
            printlog("printing_finished(%s)=%s", job, done)
            if done:
                delfile()
                return False
            if monotonic_time()-start>=PRINT_JOB_TIMEOUT:
                printlog.warn("Warning: print job %s timed out", job)
                delfile()
                return False
            return True #try again..
        if check_printing_finished():
            #check every 10 seconds:
            self.timeout_add(10000, check_printing_finished)


    def get_open_env(self):
        env = os.environ.copy()
        #prevent loops:
        env["XPRA_XDG_OPEN"] = "1"
        return env

    def _open_file(self, url):
        self.exec_open_command(url)

    def _open_url(self, url):
        if POSIX:
            #we can't use webbrowser,
            #because this will use "xdg-open" from the $PATH
            #which may point back to us!
            self.exec_open_command(url)
        else:
            import webbrowser
            webbrowser.open_new_tab(url)

    def exec_open_command(self, url):
        command = shlex.split(self.open_command)+[url]
        proc = subprocess.Popen(command, env=self.get_open_env())
        filelog("exec_open_command(%s) Popen(%s)=%s", url, command, proc)
        def open_done(*_args):
            returncode = proc.poll()
            filelog("open_file: command %s has ended, returncode=%s", command, returncode)
            if returncode!=0:
                filelog.warn("Warning: failed to open the downloaded content")
                filelog.warn(" '%s %s' returned %s", " ".join(command), returncode)
        cr = getChildReaper()
        cr.add_process(proc, "Open file %s" % url, command, True, True, open_done)

    def file_size_warning(self, action, location, basefilename, filesize, limit):
        filelog.warn("Warning: cannot %s the file '%s'", action, basefilename)
        filelog.warn(" this file is too large: %sB", std_unit(filesize, unit=1024))
        filelog.warn(" the %s file size limit is %iMB", location, limit)

    def check_file_size(self, action, filename, filesize):
        basefilename = os.path.basename(filename)
        if filesize>self.file_size_limit*1024*1024:
            self.file_size_warning(action, "local", basefilename, filesize, self.file_size_limit)
            return False
        if filesize>self.remote_file_size_limit*1024*1024:
            self.file_size_warning(action, "remote", basefilename, filesize, self.remote_file_size_limit)
            return False
        return True


    def _process_open_url(self, packet):
        url, send_id = packet[1:3]
        if not self.open_url:
            filelog.warn("Warning: received a request to open URL '%s'", url)
            filelog.warn(" but opening of URLs is disabled")
            return
        if not self.open_url_ask or self.accept_data(send_id, b"url", url, False, True):
            self._open_url(url)
        else:
            filelog("url '%s' not accepted", url)
        

    def send_open_url(self, url):
        if not self.remote_open_url:
            filelog.warn("Warning: remote end does not accept URLs")
            return False
        if self.remote_open_url_ask:
            #ask the client if it is OK to send
            return self.send_data_request("open", b"url", url)
        self.do_send_open_url(url)
        return True

    def do_send_open_url(self, url, send_id=""):
        self.send("open-url", url, send_id)

    def send_file(self, filename, mimetype, data, filesize=0, printit=False, openit=False, options={}):
        if printit:
            l = printlog
            if not self.printing:
                l.warn("Warning: printing is not enabled for %s", self)
                return False
            if not self.remote_printing:
                l.warn("Warning: remote end does not support printing")
                return False
            ask = self.remote_printing_ask
            action = "print"
        else:
            if not self.file_transfer:
                filelog.warn("Warning: file transfers are not enabled for %s", self)
                return False
            if not self.remote_file_transfer:
                printlog.warn("Warning: remote end does not support file transfers")
                return False
            l = filelog
            ask = self.remote_file_transfer_ask
            action = "upload"
            if openit:
                if not self.remote_open_files:
                    l.info("opening the file after transfer is disabled on the remote end")
                    l.info(" sending only, the file will need to be opended manually")
                    openit = False
                    action = "upload"
                else:
                    ask |= self.remote_open_files_ask
                    action = "open"
        assert len(data)>=filesize, "data is smaller then the given file size!"
        data = data[:filesize]          #gio may null terminate it
        l("send_file%s action=%s, ask=%s", (filename, mimetype, type(data), "%i bytes" % filesize, printit, openit, options), action, ask)
        self.dump_remote_caps()
        if not self.check_file_size(action, filename, filesize):
            return False
        if ask:
            return self.send_data_request(action, b"file", filename, mimetype, data, filesize, printit, openit, options)
        self.do_send_file(filename, mimetype, data, filesize, printit, openit, options)
        return True

    def send_data_request(self, action, dtype, url, mimetype="", data="", filesize=0, printit=False, openit=True, options={}):
        send_id = uuid.uuid4().hex
        if len(self.pending_send_data)>=MAX_CONCURRENT_FILES:
            filelog.warn("Warning: %s dropped", action)
            filelog.warn(" %i transfer%s already waiting for a response", len(self.pending_send_data), engs(self.pending_send_data))
            return None
        self.pending_send_data[send_id] = (dtype, url, mimetype, data, filesize, printit, openit, options)
        self.pending_send_data_timers[send_id] = self.timeout_add(self.remote_file_ask_timeout*1000, self.send_data_ask_timeout, send_id)
        filelog("sending data request for %s '%s' with send-id=%s", dtype, url, send_id)
        self.send("send-data-request", dtype, send_id, url, mimetype, filesize, printit, openit)
        return send_id


    def _process_send_data_request(self, packet):
        dtype, send_id, url, _, filesize, printit, openit = packet[1:8]
        filelog("process send-data-request: send_id=%s, url=%s, printit=%s, openit=%s", send_id, url, printit, openit)
        def cb_answer(accept):
            filelog("accept%s=%s", (url, printit, openit), accept)
            self.send("send-data-response", send_id, accept)
        if dtype==b"file":
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
        elif dtype==b"url":
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
            #fail it because if we responded with True,
            #it would fail later when we don't find this send_id in our accepted list
            cb_answer(False)
        else:
            self.ask_data_request(cb_answer, send_id, dtype, url, filesize, printit, openit)

    def ask_data_request(self, cb_answer, send_id, dtype, url, filesize, printit, openit):
        #subclasses may prompt the user here instead
        filelog("ask_data_request%s", (send_id, dtype, url, filesize, printit, openit))
        cb_answer(False)

    def _process_send_data_response(self, packet):
        send_id, accept = packet[1:3]
        filelog("process send-data-response: send_id=%s, accept=%s", send_id, accept)
        timer = self.pending_send_data_timers.get(send_id)
        if timer:
            try:
                del self.pending_send_data_timers[send_id]
            except KeyError:
                pass
            self.source_remove(timer)
        v = self.pending_send_data.get(send_id)
        if not v:
            filelog.warn("Warning: cannot find send-file entry")
            return
        try:
            del self.pending_send_data[send_id]
        except KeyError:
            pass
        dtype = v[0]
        url = v[1]
        if accept==DENY:
            filelog.info("the request to send %s '%s' has been denied", dtype, url)
            return
        else:
            assert accept in (ACCEPT, OPEN), "unknown value for send-data response: %s" % (accept,)
        if dtype==b"file":
            mimetype, data, filesize, printit, openit, options = v[2:]
            if accept==ACCEPT:
                self.do_send_file(url, mimetype, data, filesize, printit, openit, options, send_id)
            else:
                assert openit and accept==OPEN
                #try to open at this end:
                self._open_file(url)
        elif dtype==b"url":
            if accept==ACCEPT:
                self.do_send_open_url(url, send_id)
            else:
                assert accept==OPEN
                #open it at this end:
                self._open_url(url)
        else:
            filelog.error("Error: unknown datatype '%s'", dtype)

    def send_data_ask_timeout(self, send_id):
        v = self.pending_send_data_timers.get(send_id)
        if not v:
            filelog.warn("Warning: send timeout, id '%s' not found!", send_id)
            return False
        try:
            del self.pending_send_data[send_id]
            del self.pending_send_data_timers[send_id]
        except KeyError:
            pass
        filename = v[0]
        printit = v[4]
        filelog.warn("Warning: failed to %s file '%s',", ["send", "print"][printit], filename)
        filelog.warn(" the send approval request timed out")

    def do_send_file(self, filename, mimetype, data, filesize=0, printit=False, openit=False, options={}, send_id=""):
        if printit:
            action = "print"
            l = printlog
        else:
            action = "upload"
            l = filelog
        l("do_send_file%s", (filename, mimetype, type(data), "%i bytes" % filesize, printit, openit, options))
        if not self.check_file_size(action, filename, filesize):
            return False
        u = hashlib.sha1()
        u.update(data)
        absfile = os.path.abspath(filename)
        filelog("sha1 digest(%s)=%s", absfile, u.hexdigest())
        options["sha1"] = u.hexdigest()
        chunk_size = min(self.file_chunks, self.remote_file_chunks)
        if chunk_size>0 and filesize>chunk_size:
            if len(self.send_chunks_in_progress)>=MAX_CONCURRENT_FILES:
                raise Exception("too many file transfers in progress: %i" % len(self.send_chunks_in_progress))
            #chunking is supported and the file is big enough
            chunk_id = uuid.uuid4().hex
            options["file-chunk-id"] = chunk_id
            #timer to check that the other end is requesting more chunks:
            timer = self.timeout_add(CHUNK_TIMEOUT, self._check_chunk_sending, chunk_id, 0)
            chunk_state = [monotonic_time(), data, chunk_size, timer, 0]
            self.send_chunks_in_progress[chunk_id] = chunk_state
            cdata = ""
        else:
            #send everything now:
            cdata = self.compressed_wrapper("file-data", data)
            assert len(cdata)<=filesize     #compressed wrapper ensures this is true
        basefilename = os.path.basename(filename)
        #convert str to utf8 bytes:
        try:
            base = basefilename.encode("utf8")
        except:
            base = strtobytes(basefilename)
        self.send("send-file", base, mimetype, printit, openit, filesize, cdata, options, send_id)
        return True

    def _check_chunk_sending(self, chunk_id, chunk_no):
        chunk_state = self.send_chunks_in_progress.get(chunk_id)
        filelog("_check_chunk_sending(%s, %s) chunk_state found: %s", chunk_id, chunk_no, bool(chunk_state))
        if chunk_state:
            chunk_state[-2] = 0         #timer has fired
            if chunk_state[-1]==chunk_no:
                filelog.error("Error: chunked file transfer timed out on chunk %i", chunk_no)
                del self.send_chunks_in_progress[chunk_id]

    def _process_ack_file_chunk(self, packet):
        #the other end received our send-file or send-file-chunk,
        #send some more file data
        filelog("ack-file-chunk: %s", packet[1:])
        chunk_id, state, error_message, chunk = packet[1:5]
        if not state:
            filelog.error("Error: remote end is cancelling the file transfer:")
            filelog.error(" %s", error_message)
            del self.send_chunks_in_progress[chunk_id]
            return
        chunk_state = self.send_chunks_in_progress.get(chunk_id)
        if not chunk_state:
            filelog.error("Error: cannot find the file transfer id '%s'", nonl(chunk_id))
            return
        if chunk_state[-1]!=chunk:
            filelog.error("Error: chunk number mismatch (%i vs %i)", chunk_state, chunk)
            del self.send_chunks_in_progress[chunk_id]
            return
        start_time, data, chunk_size, timer, chunk = chunk_state
        if not data:
            #all sent!
            elapsed = monotonic_time()-start_time
            filelog("%i chunks of %i bytes sent in %ims (%sB/s)", chunk, chunk_size, elapsed*1000, std_unit(chunk*chunk_size/elapsed))
            del self.send_chunks_in_progress[chunk_id]
            return
        assert chunk_size>0
        #carve out another chunk:
        cdata = self.compressed_wrapper("file-data", data[:chunk_size])
        data = data[chunk_size:]
        chunk += 1
        if timer:
            self.source_remove(timer)
        timer = self.timeout_add(CHUNK_TIMEOUT, self._check_chunk_sending, chunk_id, chunk)
        self.send_chunks_in_progress[chunk_id] = [start_time, data, chunk_size, timer, chunk]
        self.send("send-file-chunk", chunk_id, chunk, cdata, bool(data))
