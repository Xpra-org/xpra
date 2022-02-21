# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import base64, binascii
from urllib.parse import urlparse
from subprocess import Popen, DEVNULL
from gi.repository import GLib

from xpra.util import envint, typedict
from xpra.os_util import OSX
from xpra.child_reaper import getChildReaper
from xpra.server.auth.sys_auth_base import SysAuthenticator, log
from xpra.platform.features import EXECUTABLE_EXTENSION
from xpra.net.websockets.handler import WebSocketRequestHandler

TIMEOUT = envint("XPRA_EXEC_AUTH_TIMEOUT", 600)


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log("exec.Authenticator(%s)", kwargs)
        self.command = kwargs.pop("command", "")
        self.timeout = kwargs.pop("timeout", TIMEOUT)
        self.http_request = kwargs.pop('http_request')
        self.timer = None
        self.proc = None
        self.timeout_event = False
        if not self.command:
            if os.name == "posix":
                auth_dialog = "/usr/libexec/xpra/auth_dialog"
            else:
                from xpra.platform.paths import get_app_dir  #pylint: disable=import-outside-toplevel
                auth_dialog = os.path.join(get_app_dir(), "auth_dialog")
            if EXECUTABLE_EXTENSION:
                #ie: add ".exe" on MS Windows
                auth_dialog += ".%s" % EXECUTABLE_EXTENSION
            log("auth_dialog=%s", auth_dialog)
            if os.path.exists(auth_dialog):
                self.command = auth_dialog
        assert self.command, "exec authentication module is not configured correctly: no command specified"
        connection = kwargs.get("connection")
        log("exec connection info: %s", connection)
        assert connection, "connection object is missing"
        self.connection_str = str(connection)
        super().__init__(**kwargs)

    def requires_challenge(self) -> bool:
        return bool(self.http_request)

    def authenticate(self, caps : typedict) -> bool:
        info = "Connection request from %s" % self.connection_str
        cmd = [self.command, info, str(self.timeout)]
        env = stdin = stdout = None
        if self.http_request:
            stdin = stdout = DEVNULL
            env = os.environ.copy()
            add_cgi_headers(env, self.http_request)
        with Popen(cmd, env=env, stdin=stdin, stdout=stdout) as proc:
            self.proc = proc
            log("authenticate(..) Popen(%s)=%s", cmd, proc)
            #if required, make sure we kill the command when it times out:
            if self.timeout>0:
                self.timer = GLib.timeout_add(self.timeout*1000, self.command_timedout)
                if not OSX:
                    #python on macos may set a 0 returncode when we use poll()
                    #so we cannot use the ChildReaper on macos,
                    #and we can't cancel the timer
                    getChildReaper().add_process(proc, "exec auth", cmd, True, True, self.command_ended)
        v = proc.returncode
        log("authenticate(..) returncode(%s)=%s", cmd, v)
        if self.timeout_event:
            return False
        return v==0

    def command_ended(self, *args):
        t = self.timer
        log("exec auth.command_ended%s timer=%s", args, t)
        if t:
            self.timer = None
            GLib.source_remove(t)

    def command_timedout(self):
        proc = self.proc
        log("exec auth.command_timedout() proc=%s", proc)
        self.timeout_event = True
        self.timer = None
        if proc:
            try:
                proc.terminate()
            except Exception:
                log("error trying to terminate exec auth process %s", proc, exc_info=True)

    def __repr__(self):
        return "exec"

def add_cgi_headers(env : dict, request : WebSocketRequestHandler):
    url = urlparse(request.path)
    parts = url.path.rsplit('/', 1)
    if len(parts)==1: # no '/', act as if there is a trailing '/'
        parts = [parts, '']

    # Not passing through any content
    env['CONTENT_TYPE'] = ''
    env['CONTENT_LENGTH'] = '0'

    # see http.server.CGIHTTPRequestHandler.run_cgi()
    # also RFC3875
    env['SERVER_SOFTWARE'] = 'XPRA'
    env['SERVER_PROTOCOL'] = request.protocol_version
    env['GATEWAY_INTERFACE'] = 'CGI/1.1'
    env['REQUEST_METHOD'] = request.command
    env['PATH_INFO'] = parts[0]
    env['PATH_TRANSLATED'] = parts[0] # TODO: window-ish path?
    env['SCRIPT_NAME'] = parts[1]
    if url.query:
        env['QUERY_STRING'] = url.query
    env['REMOTE_ADDR'] = request.client_address[0]

    # request.server not provided, and not that interesting anyway...
    #env['SERVER_NAME'] = request.server.server_name
    #env['SERVER_PORT'] = str(request.server.server_port)

    agent = request.headers.get('user-agent')
    if agent:
        env['HTTP_USER_AGENT'] = agent

    cookies = [co for co in request.headers.get_all('cookie', []) if co]
    if cookies:
        env['COOKIE'] = ', '.join(cookies)

    auth = request.headers.get("auth", "").split()
    if len(auth)==2 and auth[0].lower()=='basic':
        env['AUTH_TYPE'] = 'basic'
        try:
            # headers originally decoded as 'iso-8859-1' by http.client.parse_headers()
            # http.server.CGIHTTPRequestHandler.run_cgi() re-encodes them as 'ascii'
            # we follow parse_headers().
            # Shouldn't make any difference if payload is really base64 encoded.
            auth = base64.decodebytes(auth[1].encode('iso-8859-1')).decode()
            # we decode the output as utf-8 because everyone loves crazy password rules
            env['REMOTE_USER'], env['REMOTE_IDENT'] = auth.split(':',1)
        except (TypeError, binascii.Error, UnicodeError):
            pass

    # TODO: pass remaining headers as HTTP_* ?
