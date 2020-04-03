# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import envbool, typedict
from xpra.os_util import get_machine_id, bytestostr
from xpra.net.file_transfer import FileTransferHandler
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("printing")

ADD_LOCAL_PRINTERS = envbool("XPRA_ADD_LOCAL_PRINTERS", False)
PRINTER_LOCATION_STRING = os.environ.get("XPRA_PRINTER_LOCATION_STRING", "via xpra")

def printer_name(name):
    try:
        return name.decode("utf8")
    except Exception:
        return bytestostr(name)


class FilePrintMixin(FileTransferHandler, StubSourceMixin):

    @classmethod
    def is_needed(cls, caps : typedict) -> bool:
        return bool(caps.boolget("file-transfer") or caps.boolget("printing"))


    def init_state(self):
        self.printers = {}
        self.printers_added = set()

    def cleanup(self):
        self.remove_printers()

    def parse_client_caps(self, c : dict):
        FileTransferHandler.parse_file_transfer_caps(self, c)

    def get_info(self) -> dict:
        return {
            "printers"          : self.printers,
            "file-transfers"    : FileTransferHandler.get_info(self),
            }

    def init_from(self, _protocol, server):
        self.init_attributes()
        #copy attributes
        for x in ("file_transfer", "file_transfer_ask", "file_size_limit", "file_chunks",
                  "printing", "printing_ask", "open_files", "open_files_ask",
                  "open_url", "open_url_ask",
                  "file_ask_timeout", "open_command"):
            setattr(self, x, getattr(server.file_transfer, x))

    ######################################################################
    # printing:
    def set_printers(self, printers, password_file, auth, encryption, encryption_keyfile):
        log("set_printers(%s, %s, %s, %s, %s) for %s",
            printers, password_file, auth, encryption, encryption_keyfile, self)
        if self.machine_id==get_machine_id() and not ADD_LOCAL_PRINTERS:
            self.printers = printers
            log("local client with identical machine id,")
            log(" not configuring local printers")
            return
        if not self.uuid:
            log.warn("Warning: client did not supply a UUID,")
            log.warn(" printer forwarding cannot be enabled")
            return
        #remove the printers no longer defined
        #or those whose definition has changed (and we will re-add them):
        for k in tuple(self.printers.keys()):
            cpd = self.printers.get(k)
            npd = printers.get(k)
            if cpd==npd:
                #unchanged: make sure we don't try adding it again:
                try:
                    del printers[k]
                except KeyError:
                    pass
                continue
            if npd is None:
                log("printer %s no longer exists", k)
            else:
                log("printer %s has been modified:", k)
                log(" was %s", cpd)
                log(" now %s", npd)
            #remove it:
            try:
                del self.printers[k]
            except KeyError:
                pass
            self.remove_printer(k)
        #expand it here so the xpraforwarder doesn't need to import anything xpra:
        attributes = {"display"         : os.environ.get("DISPLAY"),
                      "source"          : self.uuid}
        def makeabs(filename):
            #convert to an absolute path since the backend may run as a different user:
            return os.path.abspath(os.path.expanduser(filename))
        if auth:
            auth_password_file = None
            try:
                name, authclass, authoptions = auth
                auth_password_file = authoptions.get("file")
                log("file for %s / %s: '%s'", name, authclass, password_file)
            except Exception as e:
                log.error("Error: cannot forward authentication attributes to printer backend:")
                log.error(" %s", e)
            if auth_password_file or password_file:
                attributes["password-file"] = makeabs(auth_password_file or password_file)
        if encryption:
            if not encryption_keyfile:
                log.error("Error: no encryption keyfile found for printing")
            else:
                attributes["encryption"] = encryption
                attributes["encryption-keyfile"] = makeabs(encryption_keyfile)
        #if we can, tell it exactly where to connect:
        if self.unix_socket_paths:
            #prefer sockets in public paths:
            attributes["socket-path"] = self.choose_socket_path()
        log("printer attributes: %s", attributes)
        for name,props in printers.items():
            printer = printer_name(name)
            if printer not in self.printers:
                self.setup_printer(printer, props, attributes)

    def choose_socket_path(self) -> str:
        assert self.unix_socket_paths
        for x in self.unix_socket_paths:
            if x.startswith("/tmp") or x.startswith("/var") or x.startswith("/run"):
                return x
        return self.unix_socket_paths[0]


    def setup_printer(self, printer, props, attributes):
        from xpra.platform.pycups_printing import add_printer
        props = typedict(props)
        info = props.strget("printer-info", "")
        attrs = attributes.copy()
        attrs["remote-printer"] = printer
        attrs["remote-device-uri"] = props.strget("device-uri")
        location = PRINTER_LOCATION_STRING
        if self.hostname:
            location = "on %s"
            if PRINTER_LOCATION_STRING:
                #ie: on FOO (via xpra)
                location = "on %s (%s)" % (self.hostname, PRINTER_LOCATION_STRING)
        try:
            def printer_added():
                #once the printer has been added, register it in the list
                #(so it will be removed on exit)
                log.info("the remote printer '%s' has been configured", printer)
                self.printers[printer] = props
                self.printers_added.add(printer)
            add_printer(printer, props, info, location, attrs, success_cb=printer_added)
        except Exception as e:
            log.warn("Warning: failed to add virtual printer '%s'", printer)
            log.warn(" %s", e)
            log("setup_printer(%s, %s, %s)", printer, props, attributes, exc_info=True)

    def remove_printers(self):
        if self.machine_id==get_machine_id() and not ADD_LOCAL_PRINTERS:
            return
        self.printers = {}
        for k in tuple(self.printers_added):
            self.remove_printer(k)

    def remove_printer(self, name):
        printer = printer_name(name)
        try:
            self.printers_added.remove(printer)
        except KeyError:
            log("not removing printer '%s' - since we didn't add it", name)
        else:
            try:
                from xpra.platform.pycups_printing import remove_printer
                remove_printer(printer)
                log.info("removed remote printer '%s'", printer)
            except Exception as e:
                log("remove_printer(%s)", printer, exc_info=True)
                log.error("Error: failed to remove printer '%s':", name)
                log.error(" %s", e)
