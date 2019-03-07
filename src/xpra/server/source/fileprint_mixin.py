# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.util import envbool
from xpra.os_util import get_machine_id, bytestostr
from xpra.net.file_transfer import FileTransferHandler
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.log import Logger

log = Logger("printing")

ADD_LOCAL_PRINTERS = envbool("XPRA_ADD_LOCAL_PRINTERS", False)
PRINTER_LOCATION_STRING = os.environ.get("XPRA_PRINTER_LOCATION_STRING", "via xpra")


class FilePrintMixin(FileTransferHandler, StubSourceMixin):

    def init_state(self):
        self.printers = {}

    def cleanup(self):
        self.remove_printers()

    def parse_client_caps(self, c):
        FileTransferHandler.parse_file_transfer_caps(self, c)

    def get_info(self):
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
            spath = self.unix_socket_paths[0]
            for x in self.unix_socket_paths:
                if x.startswith("/tmp") or x.startswith("/var") or x.startswith("/run"):
                    spath = x
            attributes["socket-path"] = spath
        log("printer attributes: %s", attributes)
        for k,props in printers.items():
            if k not in self.printers:
                self.setup_printer(k, props, attributes)

    def setup_printer(self, name, props, attributes):
        from xpra.platform.pycups_printing import add_printer
        info = props.get("printer-info", "")
        attrs = attributes.copy()
        attrs["remote-printer"] = name
        attrs["remote-device-uri"] = props.get("device-uri")
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
                log.info("the remote printer '%s' has been configured", name)
                self.printers[name] = props
            add_printer(name, props, info, location, attrs, success_cb=printer_added)
        except Exception as e:
            log.warn("Warning: failed to add printer %s: %s", bytestostr(name), e)
            log("setup_printer(%s, %s, %s)", name, props, attributes, exc_info=True)

    def remove_printers(self):
        if self.machine_id==get_machine_id() and not ADD_LOCAL_PRINTERS:
            return
        printers = self.printers.copy()
        self.printers = {}
        for k in printers:
            self.remove_printer(k)

    def remove_printer(self, printer):
        try:
            from xpra.platform.pycups_printing import remove_printer
            remove_printer(printer)
        except Exception as e:
            log("remove_printer(%s)", printer, exc_info=True)
            log.error("Error: failed to remove printer %s:", printer)
            log.error(" %s", e)
