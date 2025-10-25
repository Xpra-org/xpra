# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from urllib.parse import unquote
from collections.abc import Callable

from xpra.net.file_transfer import FileTransferHandler
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.os_util import gi_import, WIN32, POSIX
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
Gio = gi_import("Gio")

log = Logger("window", "events", "dragndrop")


def xid(w) -> int:
    # TODO: use a generic window handle function
    # this only used for debugging for now
    if w and POSIX:
        return w.get_xid()
    return 0


def drag_drop_cb(widget, context, x: int, y: int, time: int) -> None:
    targets = list(x.name() for x in context.list_targets())
    log("drag_drop_cb%s targets=%s", (widget, context, x, y, time), targets)
    if not targets:
        # this happens on macOS, but we can still get the data...
        log("Warning: no targets provided, continuing anyway")
    elif "text/uri-list" not in targets:
        log("Warning: cannot handle targets:")
        log(" %s", csv(targets))
        return
    atom = Gdk.Atom.intern("text/uri-list", False)
    widget.drag_get_data(context, atom, time)


def drag_motion_cb(wid: int, context, x: int, y: int, time: int) -> bool:
    log("drag_motion_cb(%#x, %s, %i, %i, %i)", wid, context, x, y, time)
    Gdk.drag_status(context, Gdk.DragAction.COPY, time)
    return True  # accept this data


class DragNDropWindow(GtkStubWindow):

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        # opengl probing uses a fake client,
        # in which case we don't want dragndrop initialized:
        if isinstance(client, FileTransferHandler):
            self._file_handler = client
            self.init_dragndrop()

    def is_readonly(self) -> bool:
        # inject dependency on UI client,
        # the readonly flag can be changed from the tray menu:
        return getattr(self, "readonly", False)

    ######################################################################
    # drag and drop:
    def init_dragndrop(self) -> None:
        targets = [
            Gtk.TargetEntry.new("text/uri-list", 0, 80),
        ]
        flags = Gtk.DestDefaults.MOTION | Gtk.DestDefaults.HIGHLIGHT
        actions = Gdk.DragAction.COPY  # | Gdk.ACTION_LINK
        self.drag_dest_set(flags, targets, actions)
        self.connect("drag_drop", drag_drop_cb)
        self.connect("drag_motion", drag_motion_cb)
        self.connect("drag_data_received", self.drag_got_data_cb)

    def drag_got_data_cb(self, wid: int, context, x: int, y: int, selection, info, time: int) -> None:
        log("drag_got_data_cb(%#x, %s, %i, %i, %r, %s, %i)", wid, context, x, y, selection, info, time)
        if self.is_readonly():
            return
        targets = list(x.name() for x in context.list_targets())
        actions = context.get_actions()

        dest_window = xid(context.get_dest_window())
        source_window = xid(context.get_source_window())
        suggested_action = context.get_suggested_action()
        log("drag_got_data_cb context: source_window=%#x, dest_window=%#x", source_window, dest_window)
        log(f"drag_got_data_cb context: {suggested_action=}, {actions=}, {targets=}")
        dtype = selection.get_data_type()
        fmt = selection.get_format()
        length = selection.get_length()
        target = selection.get_target()
        text = selection.get_text()
        uris = selection.get_uris()
        log("drag_got_data_cb selection: data type=%s, format=%s, length=%s, target=%s, text=%s, uris=%s",
            dtype, fmt, length, target, text, uris)
        if not uris:
            return
        filelist = []
        for uri in uris:
            if not uri:
                continue
            if not uri.startswith("file://"):
                log.warn("Warning: cannot handle drag-n-drop URI '%s'", uri)
                continue
            filename = unquote(uri[len("file://"):].rstrip("\n\r"))
            if WIN32:
                filename = filename.lstrip("/")
            abspath = os.path.abspath(filename)
            if not os.path.isfile(abspath):
                log.warn("Warning: '%s' is not a file", abspath)
                continue
            filelist.append(abspath)
        log("drag_got_data_cb: will try to upload: %s", csv(filelist))
        pending = set(filelist)

        def file_done(filename: str) -> None:
            if not pending:
                return
            try:
                pending.remove(filename)
            except KeyError:
                pass
            # when all the files have been loaded / failed,
            # finish the drag and drop context so the source knows we're done with them:
            if not pending:
                context.finish(True, False, time)

        # we may want to only process a limited number of files "at the same time":
        for filename in filelist:
            self.drag_process_file(filename, file_done)

    def drag_process_file(self, filename: str, file_done_cb: Callable) -> None:
        if self.is_readonly():
            return

        def got_file_info(gfile, result, arg=None):
            log("got_file_info(%s, %s, %s)", gfile, result, arg)
            file_info = gfile.query_info_finish(result)
            basename = gfile.get_basename()
            ctype = file_info.get_content_type()
            size = file_info.get_size()
            log("file_info(%s)=%s ctype=%s, size=%s", filename, file_info, ctype, size)

            def got_file_data(gfile, result, user_data=None) -> None:
                _, data, entity = gfile.load_contents_finish(result)
                filesize = len(data)
                log("got_file_data(%s, %s, %s) entity=%s", gfile, result, user_data, entity)
                file_done_cb(filename)
                openit = self._file_handler.remote_open_files
                log.info("sending file %s (%i bytes)", basename, filesize)
                self._file_handler.send_file(filename, "", data, filesize=filesize, openit=openit)

            cancellable = None
            user_data = (filename, True)
            gfile.load_contents_async(cancellable, got_file_data, user_data)

        try:
            gfile = Gio.File.new_for_path(path=filename)
            # basename = gf.get_basename()
            FILE_QUERY_INFO_NONE = 0
            G_PRIORITY_DEFAULT = 0
            cancellable = None
            gfile.query_info_async("standard::*", FILE_QUERY_INFO_NONE, G_PRIORITY_DEFAULT,
                                   cancellable, got_file_info, None)
        except Exception as e:
            log("file upload for %s:", filename, exc_info=True)
            log.error("Error: cannot upload '%s':", filename)
            log.estr(e)
            del e
            file_done_cb(filename)
