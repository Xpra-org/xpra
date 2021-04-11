# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_glib

from xpra.net.protocol_classes import get_server_protocol_class
from xpra.server.proxy.proxy_instance import ProxyInstance
from xpra.codecs.video_helper import getVideoHelper
from xpra.log import Logger

log = Logger("proxy")

glib = import_glib()


class ProxyInstanceThread(ProxyInstance):

    def __init__(self, session_options,
                 video_encoders, pings,
                 client_proto, server_conn,
                 disp_desc, cipher, encryption_key, caps):
        ProxyInstance.__init__(self, session_options,
                               video_encoders, pings,
                               disp_desc, cipher, encryption_key, caps)
        self.client_protocol = client_proto
        self.server_conn = server_conn


    def video_helper_init(self):
        #all threads will use just use the same settings anyway,
        #so don't re-initialize the video helper:
        self.video_helper = getVideoHelper()
        #only use video encoders (no CSC supported in proxy)
        try:
            self.video_helper.set_modules(video_encoders=self.video_encoder_modules)
        except AssertionError as e:
            log("video_helper_init() ignored: %s", e)
        else:
            self.video_helper.init()


    def __repr__(self):
        return "threaded proxy instance"


    def idle_add(self, fn, *args, **kwargs):
        return glib.idle_add(fn, *args, **kwargs)

    def timeout_add(self, timeout, fn, *args, **kwargs):
        return glib.timeout_add(timeout, fn, *args, **kwargs)

    def source_remove(self, tid):
        return glib.source_remove(tid)


    def run(self):
        log("ProxyInstanceThread.run()")
        server_protocol_class = get_server_protocol_class(self.server_conn.socktype)
        self.server_protocol = server_protocol_class(self, self.server_conn,
                                                     self.process_server_packet, self.get_server_packet)
        ProxyInstance.run(self)

    def start_network_threads(self):
        log("start_network_threads()")
        self.server_protocol.start()
        self.client_protocol._process_packet_cb = self.process_client_packet
        self.client_protocol.set_packet_source(self.get_client_packet)
        #no need to start the client protocol,
        #it was started when we processed authentication in the proxy server
        #self.client_protocol.start()


    def get_info(self):
        info = {}
        cinfo = info.setdefault("connection", {})
        def add_protocol_info(prefix, proto):
            pinfo = proto.get_info()
            cinfo[prefix] = pinfo.get("thread", ())
        add_protocol_info("client", self.client_protocol)
        add_protocol_info("server", self.server_protocol)
        return info
