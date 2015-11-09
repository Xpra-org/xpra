# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
printlog = Logger("printing")
filelog = Logger("file")

from xpra.child_reaper import getChildReaper
from xpra.util import typedict, csv

try:
    import xpra.platform.printing
    assert xpra.platform.printing
    HAS_PRINTING = True
except:
    HAS_PRINTING = False

DELETE_PRINTER_FILE = os.environ.get("XPRA_DELETE_PRINTER_FILE", "1")=="1"


class FileTransferHandler(object):
    """ Utility class for receiving files and optionally printing them,
        used by both clients and server to share the common code and attributes
    """

    def __init__(self):
        self.file_transfer = False
        self.file_size_limit = 10
        self.printing = False
        self.open_files = False
        self.open_command = None

    def init(self, opts):
        #printing and file transfer:
        self.file_transfer = opts.file_transfer
        self.file_size_limit = opts.file_size_limit
        self.printing = opts.printing
        self.open_command = opts.open_command
        self.open_files = opts.open_files


    def get_file_transfer_features(self):
        return {
                 "file-transfer"                : self.file_transfer,
                 "file-size-limit"              : self.file_size_limit,
                 "open-files"                   : self.open_files,
                 "printing"                     : self.printing,
                 }

    def get_file_transfer_info(self):
        #slightly different from above... for legacy reasons
        #this one is used in a proper "file." namespace from server_base.py
        return {
                 "transfer"                     : self.file_transfer,
                 "size-limit"                   : self.file_size_limit,
                 "open"                         : self.open_files,
                 }


    def _process_send_file(self, packet):
        #send-file basefilename, printit, openit, filesize, 0, data)
        from xpra.platform.paths import get_download_dir
        basefilename, mimetype, printit, openit, filesize, file_data, options = packet[1:11]
        options = typedict(options)
        if printit:
            l = printlog
            assert self.printing
        else:
            l = filelog
            assert self.file_transfer
        l("received file: %s", [basefilename, mimetype, printit, openit, filesize, "%s bytes" % len(file_data), options])
        assert filesize>0, "invalid file size: %s" % filesize
        assert file_data, "no data!"
        if len(file_data)!=filesize:
            l.error("Error: invalid data size for file '%s'", basefilename)
            l.error(" received %i bytes, expected %i bytes", len(file_data), filesize)
            return
        if filesize>self.file_size_limit*1024*1024:
            l.error("Error: file '%s' is too large:", basefilename)
            l.error(" %iMB, the file size limit is %iMB", filesize//1024//1024, self.file_size_limit)
            return            
        #check digest if present:
        import hashlib
        def check_digest(algo="sha1", libfn=hashlib.sha1):
            digest = options.get(algo)
            if not digest:
                return
            u = libfn()
            u.update(file_data)
            l("%s digest: %s - expected: %s", algo, u.hexdigest(), digest)
            if digest!=u.hexdigest():
                l.error("Error: data does not match, invalid %s file digest for %s", algo, basefilename)
                l.error(" received %s, expected %s", u.hexdigest(), digest)
                return
        check_digest("sha1", hashlib.sha1)
        check_digest("md5", hashlib.md5)

        #make sure we use a filename that does not exist already:
        dd = os.path.expanduser(get_download_dir())
        wanted_filename = os.path.abspath(os.path.join(dd, os.path.basename(basefilename)))
        EXTS = {"application/postscript"    : "ps",
                "application/pdf"           : "pdf",
                "raw"                       : "raw",
                }
        ext = EXTS.get(mimetype)
        if ext:
            #on some platforms (win32),
            #we want to force an extension
            #so that the file manager can display them properly when you double-click on them
            if not wanted_filename.endswith("."+ext):
                wanted_filename += "."+ext
        filename = wanted_filename
        base = 0
        while os.path.exists(filename):
            l("cannot save file as %s: file already exists", filename)
            root, ext = os.path.splitext(wanted_filename)
            base += 1
            filename = root+("-%s" % base)+ext
        flags = os.O_CREAT | os.O_RDWR | os.O_EXCL
        try:
            flags |= os.O_BINARY                #@UndefinedVariable (win32 only)
        except:
            pass
        fd = os.open(filename, flags)
        try:
            os.write(fd, file_data)
        finally:
            os.close(fd)
        l.info("downloaded %s bytes to %s file%s:", filesize, (mimetype or "unknown"), ["", " for printing"][int(printit)])
        l.info(" %s", filename)
        if printit:
            printer = options.strget("printer")
            title   = options.strget("title")
            print_options = options.dictget("options")
            #TODO: how do we print multiple copies?
            #copies = options.intget("copies")
            #whitelist of options we can forward:
            safe_print_options = dict((k,v) for k,v in print_options.items() if k in ("PageSize", "Resolution"))
            l("safe print options(%s) = %s", options, safe_print_options)
            self._print_file(filename, mimetype, printer, title, safe_print_options)
            return
        elif openit:
            self._open_file(filename)

    def _print_file(self, filename, mimetype, printer, title, options):
        import time
        from xpra.platform.printing import print_files, printing_finished, get_printers
        printers = get_printers()
        if printer not in printers:
            printlog.error("Error: printer '%s' does not exist!", printer)
            printlog.error(" printers available: %s", csv(printers.keys()) or "none")
            return
        def delfile():
            if not DELETE_PRINTER_FILE:
                return
            try:
                os.unlink(filename)
            except:
                printlog("failed to delete print job file '%s'", filename)
            return False
        job = print_files(printer, [filename], title, options)
        printlog("printing %s, job=%s", filename, job)
        if job<=0:
            printlog("printing failed and returned %i", job)
            delfile()
            return
        start = time.time()
        def check_printing_finished():
            done = printing_finished(job)
            printlog("printing_finished(%s)=%s", job, done)
            if done:
                delfile()
                return False
            if time.time()-start>10*60:
                printlog.warn("print job %s timed out", job)
                delfile()
                return False
            return True #try again..
        if check_printing_finished():
            self.timeout_add(10000, check_printing_finished)

    def _open_file(self, filename):
        if not self.open_files:
            filelog.warn("Warning: opening files automatically is disabled,")
            filelog.warn(" ignoring uploaded file:")
            filelog.warn(" '%s'", filename)
            return
        import subprocess, shlex
        command = shlex.split(self.open_command)+[filename]
        proc = subprocess.Popen(command)
        cr = getChildReaper()
        def open_done(*args):
            returncode = proc.poll()
            filelog("open_done: command %s has ended, returncode=%s", command, returncode)
            if returncode!=0:
                filelog.warn("Warning: failed to open the downloaded file")
                filelog.warn(" '%s %s' returned %s", self.open_command, filename, returncode)
        cr.add_process(proc, "Open File %s" % filename, command, True, True, open_done)
