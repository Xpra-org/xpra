# This file is part of Xpra.
# Copyright (C) 2017-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import socket
from time import sleep, monotonic
from ctypes import Structure, c_uint8, sizeof

from xpra.scripts.config import InitException, InitExit, TRUE_OPTIONS
from xpra.exit_codes import (
    EXIT_SSL_FAILURE, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE,
    EXIT_SERVER_ALREADY_EXISTS, EXIT_SOCKET_CREATION_ERROR,
    )
from xpra.net.bytestreams import set_socket_timeout, pretty_socket, SOCKET_TIMEOUT
from xpra.os_util import (
    getuid, get_username_for_uid, get_groups, get_group_id, osexpand,
    path_permission_info, umask_context, WIN32, OSX, POSIX,
    parse_encoded_bin_data,
    )
from xpra.util import (
    envint, envbool, csv, parse_simple_dict, print_nested_dict, std,
    ellipsizer, noerr,
    DEFAULT_PORT,
    )
from xpra.make_thread import start_thread

#pylint: disable=import-outside-toplevel

#what timeout value to use on the socket probe attempt:
WAIT_PROBE_TIMEOUT = envint("XPRA_WAIT_PROBE_TIMEOUT", 6)
GROUP = os.environ.get("XPRA_GROUP", "xpra")
PEEK_TIMEOUT = envint("XPRA_PEEK_TIMEOUT", 1)
PEEK_TIMEOUT_MS = envint("XPRA_PEEK_TIMEOUT_MS", PEEK_TIMEOUT*1000)
UNIXDOMAIN_PEEK_TIMEOUT_MS = envint("XPRA_UNIX_DOMAIN_PEEK_TIMEOUT_MS", 100)
PEEK_SIZE = envint("XPRA_PEEK_SIZE", 8192)

SOCKET_DIR_MODE = num = int(os.environ.get("XPRA_SOCKET_DIR_MODE", "775"), 8)
SOCKET_DIR_GROUP = os.environ.get("XPRA_SOCKET_DIR_GROUP", GROUP)


network_logger = None
def get_network_logger():
    global network_logger
    if not network_logger:
        from xpra.log import Logger
        network_logger = Logger("network")
    return network_logger


def create_unix_domain_socket(sockpath, socket_permissions=0o600):
    assert POSIX
    #convert this to a umask!
    umask = (0o777-socket_permissions) & 0o777
    listener = socket.socket(socket.AF_UNIX)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #bind the socket, using umask to set the correct permissions
    with umask_context(umask):
        listener.bind(sockpath)
    try:
        inode = os.stat(sockpath).st_ino
    except OSError:
        inode = -1
    #set to the "xpra" group if we are a member of it, or if running as root:
    uid = getuid()
    username = get_username_for_uid(uid)
    groups = get_groups(username)
    if uid==0 or GROUP in groups:
        group_id = get_group_id(GROUP)
        if group_id>=0:
            try:
                os.lchown(sockpath, -1, group_id)
            except Exception as e:
                log = get_network_logger()
                log.warn("Warning: failed to set '%s' group ownership", GROUP)
                log.warn(" on socket '%s':", sockpath)
                log.warn(" %s", e)
            #don't know why this doesn't work:
            #os.fchown(listener.fileno(), -1, group_id)
    def cleanup_socket():
        log = get_network_logger()
        try:
            cur_inode = os.stat(sockpath).st_ino
        except OSError:
            log.info("socket '%s' already deleted", sockpath)
            return
        delpath = sockpath
        log("cleanup_socket '%s', original inode=%s, new inode=%s", sockpath, inode, cur_inode)
        if cur_inode==inode:
            log.info("removing unix domain socket '%s'", delpath)
            try:
                os.unlink(delpath)
            except OSError:
                pass
    return listener, cleanup_socket

def has_dual_stack() -> bool:
    """
        Return True if kernel allows creating a socket which is able to
        listen for both IPv4 and IPv6 connections.
        If *sock* is provided the check is made against it.
    """
    try:
        assert socket.AF_INET6 and socket.IPPROTO_IPV6 and socket.IPV6_V6ONLY
    except AttributeError:
        return False
    try:
        import contextlib
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        with contextlib.closing(sock):
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, False)
            return True
    except socket.error:
        return False

def hosts(host_str):
    if host_str=="*":
        if has_dual_stack():
            #IPv6 will also listen for IPv4:
            return ["::"]
        #no dual stack, so we have to listen on both IPv4 and IPv6 explicitly:
        return ["0.0.0.0", "::"]
    return [host_str]

def add_listen_socket(socktype, sock, info, new_connection_cb, options=None):
    log = get_network_logger()
    log("add_listen_socket%s", (socktype, sock, info, new_connection_cb, options))
    try:
        #ugly that we have different ways of starting sockets,
        #TODO: abstract this into the socket class
        if socktype=="named-pipe":
            #named pipe listener uses a thread:
            sock.new_connection_cb = new_connection_cb
            sock.start()
            return None
        sources = []
        from gi.repository import GLib
        sock.listen(5)
        def io_in_cb(sock, flags):
            log("io_in_cb(%s, %s)", sock, flags)
            return new_connection_cb(socktype, sock)
        source = GLib.io_add_watch(sock, GLib.PRIORITY_DEFAULT, GLib.IO_IN, io_in_cb)
        sources.append(source)
        upnp_cleanup = []
        if socktype in ("tcp", "ws", "wss", "ssh", "ssl"):
            upnp = (options or {}).get("upnp", "no")
            if upnp.lower() in TRUE_OPTIONS:
                from xpra.net.upnp import upnp_add
                upnp_cleanup.append(upnp_add(socktype, info, options))
        def cleanup():
            for source in tuple(sources):
                GLib.source_remove(source)
                sources.remove(source)
            for c in upnp_cleanup:
                if c:
                    start_thread(c, "pnp-cleanup-%s" % c, daemon=True)
        return cleanup
    except Exception as e:
        log("add_listen_socket%s", (socktype, sock, info, new_connection_cb, options), exc_info=True)
        log.error("Error: failed to listen on %s socket %s:", socktype, info or sock)
        log.error(" %s", e)
        return None


def accept_connection(socktype, listener, timeout=None, socket_options=None):
    log = get_network_logger()
    try:
        sock, address = listener.accept()
    except socket.error as e:
        log("rejecting new connection on %s", listener, exc_info=True)
        log.error("Error: cannot accept new connection:")
        log.error(" %s", e)
        return None
    #log("peercred(%s)=%s", sock, get_peercred(sock))
    try:
        peername = sock.getpeername()
    except OSError:
        peername = address
    sock.settimeout(timeout)
    sockname = sock.getsockname()
    from xpra.net.bytestreams import SocketConnection
    conn = SocketConnection(sock, sockname, address, peername, socktype, None, socket_options)
    log("accept_connection(%s, %s, %s)=%s", listener, socktype, timeout, conn)
    return conn

def peek_connection(conn, timeout=PEEK_TIMEOUT_MS, size=PEEK_SIZE):
    log = get_network_logger()
    log("peek_connection(%s, %i, %i)", conn, timeout, size)
    peek_data = b""
    start = monotonic()
    elapsed = 0
    set_socket_timeout(conn, PEEK_TIMEOUT_MS/1000)
    while elapsed<=timeout:
        try:
            peek_data = conn.peek(size)
            if peek_data:
                break
        except OSError:
            log("peek_connection(%s, %i) failed", conn, timeout, exc_info=True)
        except ValueError:
            log("peek_connection(%s, %i) failed", conn, timeout, exc_info=True)
            break
        sleep(timeout/4000.0)
        elapsed = int(1000*(monotonic()-start))
        log("peek: elapsed=%s, timeout=%s", elapsed, timeout)
    log("socket %s peek: got %i bytes", conn, len(peek_data))
    return peek_data


POSIX_TCP_INFO = (
        ("state",           c_uint8),
        )
def get_sockopt_tcp_info(sock, TCP_INFO, attributes=POSIX_TCP_INFO):
    def get_tcpinfo_class(fields):
        class TCPInfo(Structure):
            _fields_ = tuple(fields)
            def __repr__(self):
                return "TCPInfo(%s)" % self.getdict()
            def getdict(self):
                return {k[0] : getattr(self, k[0]) for k in self._fields_}
        return TCPInfo
    #calculate full structure size with all the fields defined:
    tcpinfo_class = get_tcpinfo_class(attributes)
    tcpinfo_size = sizeof(tcpinfo_class)
    data = sock.getsockopt(socket.SOL_TCP, TCP_INFO, tcpinfo_size)
    data_size = len(data)
    #but only define fields in the ctypes.Structure
    #if they are actually present in the returned data:
    while tcpinfo_size>data_size:
        #trim it down:
        attributes = attributes[:-1]
        tcpinfo_class = get_tcpinfo_class(attributes)
        tcpinfo_size = sizeof(tcpinfo_class)
    log = get_network_logger()
    if tcpinfo_size==0:
        log("getsockopt(SOL_TCP, TCP_INFO, %i) no data", tcpinfo_size)
        return {}
    #log("total size=%i for fields: %s", size, csv(fdef[0] for fdef in fields))
    try:
        tcpinfo = tcpinfo_class.from_buffer_copy(data[:tcpinfo_size])
    except ValueError as e:
        log("getsockopt(SOL_TCP, TCP_INFO, %i)", tcpinfo_size, exc_info=True)
        log("TCPInfo fields=%s", csv(attributes))
        log.warn("Warning: failed to get TCP_INFO for %s", sock)
        log.warn(" %s", e)
        return {}
    d = tcpinfo.getdict()
    log("getsockopt(SOL_TCP, TCP_INFO, %i)=%s", tcpinfo_size, d)
    return d



def guess_packet_type(data):
    if not data:
        return None
    if data[0]==ord("P"):
        from xpra.net.header import (
            unpack_header, HEADER_SIZE,
            FLAGS_RENCODE, FLAGS_YAML,
            LZ4_FLAG, BROTLI_FLAG,
            )
        header = data.ljust(HEADER_SIZE, b"\0")
        _, protocol_flags, compression_level, packet_index, data_size = unpack_header(header)
        #this normally used on the first packet, so the packet index should be 0
        #and I don't think we can make packets smaller than 8 bytes,
        #even with packet name aliases and rencode
        #(and aliases should not be defined for the initial packet anyway)
        if packet_index==0 and 8<data_size<256*1024*1024:
            rencode = bool(protocol_flags & FLAGS_RENCODE)
            yaml = bool(protocol_flags & FLAGS_YAML)
            lz4 = bool(protocol_flags & LZ4_FLAG)
            brotli = bool(protocol_flags & BROTLI_FLAG)
            def is_xpra():
                compressors = sum((lz4, brotli))
                #only one compressor can be enabled:
                if compressors>1:
                    return False
                if compressors==1 and compression_level<=0:
                    #if compression is enabled, the compression level must be set:
                    return False
                if rencode and yaml:
                    #rencode and yaml are mutually exclusive:
                    return False
                return True
            if is_xpra():
                return "xpra"
    if data[:4]==b"SSH-":
        return "ssh"
    if data[0]==0x16:
        return "ssl"
    if data[:4]==b"RFB ":
        return "vnc"
    line1 = data.splitlines()[0]
    if line1.find(b"HTTP/")>0 or line1.split(b" ")[0] in (b"GET", b"POST"):
        return "http"
    if line1.lower().startswith(b"<!doctype html") or line1.lower().startswith(b"<html"):
        return "http"
    return None


def create_sockets(opts, error_cb, retry=0):
    bind_tcp = parse_bind_ip(opts.bind_tcp)
    bind_ssl = parse_bind_ip(opts.bind_ssl, 443)
    bind_ssh = parse_bind_ip(opts.bind_ssh, 22)
    bind_ws  = parse_bind_ip(opts.bind_ws, 80)
    bind_wss = parse_bind_ip(opts.bind_wss, 443)
    bind_rfb = parse_bind_ip(opts.bind_rfb, 5900)
    bind_vsock = parse_bind_vsock(opts.bind_vsock)

    min_port = int(opts.min_port)
    # Initialize the TCP sockets before the display,
    # That way, errors won't make us kill the Xvfb
    # (which may not be ours to kill at that point)
    ssh_upgrades = opts.ssh_upgrade
    if ssh_upgrades:
        try:
            from xpra.net.ssh import nogssapi_context
            with nogssapi_context():
                import paramiko
            assert paramiko
        except ImportError as e:
            from xpra.log import Logger
            sshlog = Logger("ssh")
            sshlog("import paramiko", exc_info=True)
            sshlog.error("Error: cannot enable SSH socket upgrades:")
            sshlog.error(" %s", e)
            ssh_upgrades = False
    log = get_network_logger()
    #prepare tcp socket definitions:
    tcp_defs = []
    for socktype, defs in {
        "tcp"   : bind_tcp,
        "ssl"   : bind_ssl,
        "ssh"   : bind_ssh,
        "ws"    : bind_ws,
        "wss"   : bind_wss,
        "rfb"   : bind_rfb,
        }.items():
        log("setting up %s sockets: %s", socktype, csv(defs.items()))
        for (host, iport), options in defs.items():
            if iport!=0 and iport<min_port:
                error_cb("invalid %s port number %i (minimum value is %i)" % (socktype, iport, min_port))
            for h in hosts(host):
                tcp_defs.append((socktype, h, iport, options, None))

    sockets = {}
    for attempt in range(retry+1):
        if not tcp_defs:
            break
        try_list = tuple(tcp_defs)
        tcp_defs = []
        for socktype, host, iport, options, _ in try_list:
            try:
                sock = setup_tcp_socket(host, iport, socktype)
            except Exception as e:
                log("setup_tcp_socket%s attempt=%s", (host, iport, options), attempt)
                tcp_defs.append((socktype, host, iport, options, e))
            else:
                host, iport = sock[2]
                sockets[sock] = options
        if tcp_defs:
            sleep(1)
    if tcp_defs:
        #failed to create some sockets:
        for socktype, host, iport, options, exception in tcp_defs:
            log.error("Error creating %s socket", socktype)
            log.error(" on %s:%s", host, iport)
            log.error(" %s", exception)
            raise InitException("failed to create %s socket: %s" % (socktype, exception))

    log("setting up vsock sockets: %s", csv(bind_vsock.items()))
    for (cid, iport), options in bind_vsock.items():
        sock = setup_vsock_socket(cid, iport)
        sockets[sock] = options

    # systemd socket activation:
    if POSIX and not OSX:
        try:
            from xpra.platform.xposix.sd_listen import get_sd_listen_sockets
        except ImportError as e:
            log("no systemd socket activation: %s", e)
        else:
            sd_sockets = get_sd_listen_sockets()
            log("systemd sockets: %s", sd_sockets)
            for stype, sock, addr in sd_sockets:
                sock = setup_sd_listen_socket(stype, sock, addr)
                sockets[sock] = {}
                log("%s : %s", (stype, [addr]), sock)
    return sockets

def create_tcp_socket(host, iport):
    log = get_network_logger()
    if host.find(":")<0:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockaddr = (host, iport)
    else:
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        assert socket.has_ipv6, "specified an IPv6 address but this is not supported"
        res = socket.getaddrinfo(host, iport, socket.AF_INET6, socket.SOCK_STREAM, 0, socket.SOL_TCP)
        log("socket.getaddrinfo(%s, %s, AF_INET6, SOCK_STREAM, 0, SOL_TCP)=%s", host, iport, res)
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sockaddr = res[0][-1]
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    log("%s.bind(%s)", listener, sockaddr)
    listener.bind(sockaddr)
    return listener

def setup_tcp_socket(host, iport, socktype="tcp"):
    log = get_network_logger()
    try:
        tcp_socket = create_tcp_socket(host, iport)
    except Exception as e:
        log("create_tcp_socket%s", (host, iport), exc_info=True)
        raise InitExit(EXIT_SOCKET_CREATION_ERROR,
                       "failed to setup %s socket on %s:%s %s" % (socktype, host, iport, e)) from None
    def cleanup_tcp_socket():
        log.info("closing %s socket '%s:%s'", socktype.lower(), host, iport)
        try:
            tcp_socket.close()
        except OSError:
            pass
    if iport==0:
        iport = tcp_socket.getsockname()[1]
        log.info("allocated %s port %i on %s", socktype, iport, host)
    log("%s: %s:%s : %s", socktype, host, iport, socket)
    log.info("created %s socket '%s:%s'", socktype, host, iport)
    return socktype, tcp_socket, (host, iport), cleanup_tcp_socket

def parse_bind_ip(bind_ip, default_port=DEFAULT_PORT):
    ip_sockets = {}
    if bind_ip:
        for spec in bind_ip:
            parts = spec.split(",", 1)
            ip_port = parts[0]
            if ":" not in spec:
                raise InitException("port must be specified as [HOST]:PORT")
            host, port = ip_port.rsplit(":", 1)
            if host == "":
                host = "127.0.0.1"
            if not port:
                iport = default_port
            elif port=="0":
                iport = 0
            else:
                try:
                    iport = int(port)
                    assert 0<iport<2**16
                except (TypeError, ValueError):
                    raise InitException("invalid port number: %s" % port) from None
            options = {}
            if len(parts)==2:
                options = parse_simple_dict(parts[1])
            ip_sockets[(host, iport)] = options
    return ip_sockets

def setup_vsock_socket(cid, iport):
    log = get_network_logger()
    try:
        from xpra.net.vsock import bind_vsocket     #@UnresolvedImport
        vsock_socket = bind_vsocket(cid=cid, port=iport)
    except Exception as e:
        raise InitExit(EXIT_SOCKET_CREATION_ERROR,
                       "failed to setup vsock socket on %s:%s %s" % (cid, iport, e)) from None
    def cleanup_vsock_socket():
        log.info("closing vsock socket %s:%s", cid, iport)
        try:
            vsock_socket.close()
        except OSError:
            pass
    return "vsock", vsock_socket, (cid, iport), cleanup_vsock_socket

def parse_bind_vsock(bind_vsock):
    vsock_sockets = {}
    if bind_vsock:
        from xpra.scripts.parsing import parse_vsock  #pylint: disable=import-outside-toplevel
        for spec in bind_vsock:
            parts = spec.split(",", 1)
            cid, iport = parse_vsock(parts[0])
            options = {}
            if len(parts)==2:
                options = parse_simple_dict(parts[1])
            vsock_sockets[(cid, iport)] = options
    return vsock_sockets

def setup_sd_listen_socket(stype, sock, addr):
    log = get_network_logger()
    def cleanup_sd_listen_socket():
        log.info("closing sd listen socket %s", pretty_socket(addr))
        try:
            sock.close()
        except OSError:
            pass
    return stype, sock, addr, cleanup_sd_listen_socket


def normalize_local_display_name(local_display_name):
    pos = local_display_name.find(":")
    if pos<0:
        after_sc = local_display_name
        local_display_name = ":" + local_display_name
    else:
        after_sc = local_display_name[pos+1:]
    if WIN32 or OSX:
        if after_sc.isalnum():
            return local_display_name
        raise Exception("non alphanumeric character in display name '%s'" % local_display_name)
    #we used to strip the screen from the display string, ie: ":0.0" -> ":0"
    #but now we allow it.. (untested!)
    for char in after_sc:
        assert char in "0123456789.", "invalid character in display name '%s': %s" % (local_display_name, char)
    return local_display_name


def setup_local_sockets(bind, socket_dir, socket_dirs, display_name, clobber,
                        mmap_group="auto", socket_permissions="600", username="", uid=0, gid=0):
    log = get_network_logger()
    log("setup_local_sockets%s", (bind, socket_dir, socket_dirs, display_name, clobber,
                                  mmap_group, socket_permissions, username, uid, gid))
    if not bind:
        return {}
    if not socket_dir and (not socket_dirs or (len(socket_dirs)==1 and not socket_dirs[0])):
        if WIN32:
            socket_dirs = [""]
        else:
            raise InitExit(EXIT_SOCKET_CREATION_ERROR,
                           "at least one socket directory must be set to use unix domain sockets")
    from xpra.platform.dotxpra import DotXpra, norm_makepath
    dotxpra = DotXpra(socket_dir or socket_dirs[0], socket_dirs, username, uid, gid)
    if display_name is not None and not WIN32:
        display_name = normalize_local_display_name(display_name)
    defs = {}
    try:
        sockpaths = {}
        log("setup_local_sockets: bind=%s, dotxpra=%s", bind, dotxpra)
        for b in bind:
            if b in ("none", ""):
                continue
            parts = b.split(",")
            sockpath = parts[0]
            options = {}
            if len(parts)==2:
                options = parse_simple_dict(parts[1])
            if sockpath=="auto":
                assert display_name is not None
                for sockpath in dotxpra.norm_socket_paths(display_name):
                    sockpaths[sockpath] = options
                log("sockpaths(%s)=%s (uid=%i, gid=%i)", display_name, sockpaths, uid, gid)
            else:
                sockpath = dotxpra.osexpand(sockpath)
                if sockpath.endswith("/") or (os.path.exists(sockpath) and os.path.isdir(sockpath)):
                    assert display_name is not None
                    sockpath = os.path.abspath(sockpath)
                    if not os.path.exists(sockpath):
                        os.makedirs(sockpath)
                    sockpath = norm_makepath(sockpath, display_name)
                elif os.path.isabs(sockpath):
                    pass
                else:
                    sockpath = dotxpra.socket_path(sockpath)
                sockpaths[sockpath] = options
            assert sockpaths, "no socket paths to try for %s" % b
        #expand and remove duplicate paths:
        tmp = {}
        for tsp, options in sockpaths.items():
            sockpath = dotxpra.osexpand(tsp)
            if sockpath in tmp:
                log.warn("Warning: skipping duplicate bind path %s", sockpath)
                continue
            tmp[sockpath] = options
        sockpaths = tmp
        log("sockpaths=%s", sockpaths)
        #create listeners:
        if WIN32:
            from xpra.platform.win32.namedpipes.listener import NamedPipeListener
            from xpra.platform.win32.dotxpra import PIPE_PATH
            for sockpath, options in sockpaths.items():
                npl = NamedPipeListener(sockpath)
                ppath = sockpath
                if ppath.startswith(PIPE_PATH):
                    ppath = ppath[len(PIPE_PATH):]
                log.info("created named pipe '%s'", ppath)
                defs[("named-pipe", npl, sockpath, npl.stop)] = options
        else:
            def checkstate(sockpath, state):
                if state not in (DotXpra.DEAD, DotXpra.UNKNOWN):
                    if state==DotXpra.INACCESSIBLE:
                        raise InitException("An xpra server is already running at %s\n" % (sockpath,))
                    raise InitExit(EXIT_SERVER_ALREADY_EXISTS,
                                   "You already have an xpra server running at %s\n"
                                   "  (did you want 'xpra upgrade'?)"
                                   % (sockpath,))
            #remove exisiting sockets if clobber is set,
            #otherwise verify there isn't a server already running
            #and create the directories for the sockets:
            unknown = []
            for sockpath in sockpaths:
                if clobber and os.path.exists(sockpath):
                    os.unlink(sockpath)
                else:
                    state = dotxpra.get_server_state(sockpath, 1)
                    log("state(%s)=%s", sockpath, state)
                    checkstate(sockpath, state)
                    if state==dotxpra.UNKNOWN:
                        unknown.append(sockpath)
                d = os.path.dirname(sockpath)
                try:
                    kwargs = {}
                    if d in ("/var/run/xpra", "/run/xpra"):
                        #this is normally done by tmpfiles.d,
                        #but we may need to do it ourselves in some cases:
                        kwargs["mode"] = SOCKET_DIR_MODE
                        xpra_gid = get_group_id(SOCKET_DIR_GROUP)
                        if xpra_gid>0:
                            kwargs["gid"] = xpra_gid
                    log("creating sockdir=%s, kwargs=%s" % (d, kwargs))
                    dotxpra.mksockdir(d, **kwargs)
                    log("%s permission mask: %s", d, oct(os.stat(d).st_mode))
                except Exception as e:
                    log.warn("Warning: failed to create socket directory '%s'", d)
                    log.warn(" %s", e)
                    del e
            #wait for all the unknown ones:
            log("sockets in unknown state: %s", unknown)
            if unknown:
                #re-probe them using threads so we can do them in parallel:
                threads = []
                def timeout_probe(sockpath):
                    #we need a loop because "DEAD" sockets may return immediately
                    #(ie: when the server is starting up)
                    start = monotonic()
                    while monotonic()-start<WAIT_PROBE_TIMEOUT:
                        state = dotxpra.get_server_state(sockpath, WAIT_PROBE_TIMEOUT)
                        log("timeout_probe() get_server_state(%s)=%s", sockpath, state)
                        if state not in (DotXpra.UNKNOWN, DotXpra.DEAD):
                            break
                        sleep(1)
                log.warn("Warning: some of the sockets are in an unknown state:")
                for sockpath in unknown:
                    log.warn(" %s", sockpath)
                    t = start_thread(timeout_probe, "probe-%s" % sockpath, daemon=True, args=(sockpath,))
                    threads.append(t)
                log.warn(" please wait as we allow the socket probing to timeout")
                #wait for all the threads to do their job:
                for t in threads:
                    t.join(WAIT_PROBE_TIMEOUT+1)
            if sockpaths:
                #now we can re-check quickly:
                #(they should all be DEAD or UNKNOWN):
                for sockpath in sockpaths:
                    state = dotxpra.get_server_state(sockpath, 1)
                    log("state(%s)=%s", sockpath, state)
                    checkstate(sockpath, state)
                    try:
                        if os.path.exists(sockpath):
                            os.unlink(sockpath)
                    except OSError:
                        pass
                #socket permissions:
                if mmap_group.lower() in TRUE_OPTIONS:
                    #when using the mmap group option, use '660'
                    sperms = 0o660
                else:
                    #parse octal mode given as config option:
                    try:
                        if isinstance(socket_permissions, int):
                            sperms = socket_permissions
                        else:
                            #assume octal string:
                            sperms = int(socket_permissions, 8)
                        assert 0<=sperms<=0o777, "invalid socket permission value %s" % oct(sperms)
                    except ValueError:
                        raise ValueError("invalid socket permissions "+
                                         "(must be an octal number): '%s'" % socket_permissions) from None
                #now try to create all the sockets:
                for sockpath, options in sockpaths.items():
                    #create it:
                    try:
                        sock, cleanup_socket = create_unix_domain_socket(sockpath, sperms)
                        log.info("created unix domain socket '%s'", sockpath)
                        defs[("unix-domain", sock, sockpath, cleanup_socket)] = options
                    except Exception as e:
                        handle_socket_error(sockpath, sperms, e)
                        del e
    except Exception:
        for sock, cleanup_socket in defs.items():
            try:
                cleanup_socket()
            except Exception:
                log.error("Error cleaning up socket %s:", sock, exc_info=True)
                log.error(" using %s", cleanup_socket)
        raise
    return defs

def handle_socket_error(sockpath, sperms, e):
    log = get_network_logger()
    log("socket creation error", exc_info=True)
    if sockpath.startswith("/var/run/xpra") or sockpath.startswith("/run/xpra"):
        log.info("cannot create group socket '%s'", sockpath)
        log.info(" %s", e)
        dirname = sockpath[:sockpath.find("xpra")+len("xpra")]
        if not os.path.exists(dirname):
            log.info(" %s does not exist", dirname)
        #only show extra information if the socket permissions
        #would have been accessible by the group:
        elif POSIX and (sperms & 0o40):
            uid = getuid()
            username = get_username_for_uid(uid)
            groups = get_groups(username)
            log.info(" user '%s' is a member of groups: %s", username, csv(groups) or "no groups!")
            if "xpra" not in groups:
                log.info("  add 'xpra' group membership to enable group socket sharing")
            for x in path_permission_info(dirname):
                log.info("  %s", x)
    elif sockpath.startswith("/var/run/user") or sockpath.startswith("/run/user"):
        log.warn("Warning: cannot create socket '%s':", sockpath)
        log.warn(" %s", e)
        run_user = sockpath.split("/user")[0]+"/user"
        if not os.path.exists(run_user):
            log.warn(" %s does not exist", run_user)
        else:
            log.warn(" ($XDG_RUNTIME_DIR has not been created?)")
    else:
        log.error("Error: failed to create socket '%s':", sockpath)
        log.error(" %s", e)
        raise InitExit(EXIT_SOCKET_CREATION_ERROR,
                       "failed to create socket %s" % sockpath)


#warn just once:
MDNS_WARNING = False
def mdns_publish(display_name, listen_on, text_dict=None):
    global MDNS_WARNING
    if MDNS_WARNING is True:
        return ()
    from xpra.log import Logger
    log = Logger("mdns")
    log("mdns_publish%s", (display_name, listen_on, text_dict))
    try:
        from xpra.net import mdns
        assert mdns
        from xpra.net.mdns import XPRA_MDNS_TYPE, RFB_MDNS_TYPE
        PREFER_ZEROCONF = envbool("XPRA_PREFER_ZEROCONF", True)
        if PREFER_ZEROCONF:
            from xpra.net.mdns.zeroconf_publisher import ZeroconfPublishers as MDNSPublishers, get_interface_index
        else:
            from xpra.net.mdns.avahi_publisher import AvahiPublishers as MDNSPublishers, get_interface_index
    except ImportError as e:
        MDNS_WARNING = True
        log("mdns import failure", exc_info=True)
        log.warn("Warning: failed to load the mdns publisher")
        try:
            einfo = str(e)
        except Exception:
            einfo = str(type(e))
        log.warn(" %s", einfo)
        log.warn(" either install the 'python-avahi' module")
        log.warn(" or use the 'mdns=no' option")
        return ()
    d = dict(text_dict or {})
    #ensure we don't have duplicate interfaces:
    f_listen_on = {}
    for host, port in listen_on:
        f_listen_on[(get_interface_index(host), port)] = (host, port)
    try:
        name = socket.gethostname()
    except OSError:
        name = "Xpra"
    if display_name and not (OSX or WIN32):
        name += " %s" % display_name
    mode = d.get("mode", "tcp")
    service_type = {"rfb" : RFB_MDNS_TYPE}.get(mode, XPRA_MDNS_TYPE)
    index = 0
    aps = []
    for host, port in listen_on:
        sn = name
        mode_str = mode
        if index>0:
            mode_str = "%s-%i" % (mode, index+1)
        if mode not in ("tcp", "rfb"):
            sn += " (%s)" % mode_str
        listen = ( (host, port), )
        index += 1
        aps.append(MDNSPublishers(listen, sn, service_type=service_type, text_dict=d))
    return aps


SSL_ATTRIBUTES = (
    "cert", "key", "ca_certs", "ca_data",
    "protocol",
    "client_verify_mode", "server_verify_mode", "verify_flags",
    "check_hostname", "server_hostname",
    "options", "ciphers",
    )

def get_ssl_attributes(opts, server_side=True, overrides=None):
    args = {
        "server_side"   : server_side,
        }
    for attr in SSL_ATTRIBUTES:
        ssl_attr = "ssl_%s" % attr          #ie: "ssl_ca_certs"
        option = ssl_attr.replace("_", "-") #ie: "ssl-ca-certs"
        v = (overrides or {}).get(option)
        if v is None:
            v = getattr(opts, ssl_attr)
        args[attr] = v
    return args

def find_ssl_cert(filename="ssl-cert.pem"):
    from xpra.log import Logger
    ssllog = Logger("ssl")
    #try to locate the cert file from known locations
    from xpra.platform.paths import get_ssl_cert_dirs  #pylint: disable=import-outside-toplevel
    dirs = get_ssl_cert_dirs()
    ssllog("find_ssl_cert(%s) get_ssl_cert_dirs()=%s", filename, dirs)
    for d in dirs:
        p = osexpand(d)
        if not os.path.exists(p):
            ssllog("ssl cert dir '%s' does not exist", p)
            continue
        f = os.path.join(p, "ssl-cert.pem")
        if not os.path.exists(f):
            ssllog("ssl cert '%s' does not exist", f)
            continue
        if not os.path.isfile(f):
            ssllog.warn("Warning: '%s' is not a file", f)
            continue
        if not os.access(p, os.R_OK):
            ssllog.info("SSL certificate file '%s' is not accessible", f)
            continue
        ssllog("found ssl cert '%s'", f)
        return f
    return None

def ssl_wrap_socket(sock, **kwargs):
    context, wrap_kwargs = get_ssl_wrap_socket_context(**kwargs)
    return do_wrap_socket(sock, context, **wrap_kwargs)

def log_ssl_info(ssl_sock):
    from xpra.log import Logger
    ssllog = Logger("ssl")
    ssllog("server_hostname=%s", ssl_sock.server_hostname)
    cipher = ssl_sock.cipher()
    if cipher:
        ssllog.info(" %s, %s bits", cipher[0], cipher[2])
    try:
        cert = ssl_sock.getpeercert()
    except ValueError:
        pass
    else:
        if cert:
            ssllog.info("certificate:")
            print_nested_dict(ssl_sock.getpeercert(), prefix=" ", print_fn=ssllog.info)

SSL_VERIFY_EXPIRED = 10
SSL_VERIFY_WRONG_HOST = 20
SSL_VERIFY_SELF_SIGNED = 18
SSL_VERIFY_UNTRUSTED_ROOT = 19
SSL_VERIFY_IP_MISMATCH = 64
SSL_VERIFY_CODES = {
    SSL_VERIFY_EXPIRED          : "expired",    #also revoked!
    SSL_VERIFY_WRONG_HOST       : "wrong host",
    SSL_VERIFY_SELF_SIGNED      : "self-signed",
    SSL_VERIFY_UNTRUSTED_ROOT   : "untrusted-root",
    SSL_VERIFY_IP_MISMATCH      : "ip-mismatch",
    }

class SSLVerifyFailure(InitExit):
    def __init__(self, status, msg, verify_code, ssl_sock):
        super().__init__(status, msg)
        self.verify_code = verify_code
        self.ssl_sock = ssl_sock

def ssl_handshake(ssl_sock):
    from xpra.log import Logger
    ssllog = Logger("ssl")
    try:
        ssl_sock.do_handshake(True)
        ssllog.info("SSL handshake complete, %s", ssl_sock.version())
        log_ssl_info(ssl_sock)
    except Exception as e:
        ssllog("do_handshake", exc_info=True)
        log_ssl_info(ssl_sock)
        import ssl
        SSLEOFError = getattr(ssl, "SSLEOFError", None)
        if SSLEOFError and isinstance(e, SSLEOFError):
            return None
        status = EXIT_SSL_FAILURE
        SSLCertVerificationError = getattr(ssl, "SSLCertVerificationError", None)
        if SSLCertVerificationError and isinstance(e, SSLCertVerificationError):
            verify_code = getattr(e, "verify_code", 0)
            ssllog("verify_code=%s", SSL_VERIFY_CODES.get(verify_code, verify_code))
            try:
                msg = getattr(e, "verify_message") or (e.args[1].split(":", 2)[2])
            except (ValueError, IndexError):
                msg = str(e)
            status = EXIT_SSL_CERTIFICATE_VERIFY_FAILURE
            ssllog("host failed SSL verification: %s", msg)
            raise SSLVerifyFailure(status, msg, verify_code, ssl_sock) from None
        raise InitExit(status, "SSL handshake failed: %s" % str(e)) from None
    return ssl_sock

def get_ssl_wrap_socket_context(cert=None, key=None, ca_certs=None, ca_data=None,
                        protocol="TLSv1_2",
                        client_verify_mode="optional", server_verify_mode="required", verify_flags="X509_STRICT",
                        check_hostname=False, server_hostname=None,
                        options="ALL,NO_COMPRESSION", ciphers="DEFAULT",
                        server_side=True):
    if server_side and not cert:
        raise InitException("you must specify an 'ssl-cert' file to use ssl sockets")
    if server_side:
        verify_mode = client_verify_mode
    else:
        verify_mode = server_verify_mode
    from xpra.log import Logger
    ssllog = Logger("ssl")
    ssllog("get_ssl_wrap_socket_context%s", (cert, key, ca_certs, ca_data,
                                    protocol,
                                    client_verify_mode, server_verify_mode, verify_flags,
                                    check_hostname, server_hostname,
                                    options, ciphers,
                                    server_side))
    import ssl
    ssllog(" verify_mode for server_side=%s : %s", server_side, verify_mode)
    #ca-certs:
    if ca_certs=="default":
        ca_certs = None
    elif ca_certs=="auto":
        ca_certs = find_ssl_cert("ca-cert.pem")
    ssllog(" ca_certs=%s", ca_certs)
    #parse verify-mode:
    ssl_cert_reqs = getattr(ssl, "CERT_%s" % verify_mode.upper(), None)
    if ssl_cert_reqs is None:
        values = [k[len("CERT_"):].lower() for k in dir(ssl) if k.startswith("CERT_")]
        raise InitException("invalid ssl-server-verify-mode '%s', must be one of: %s" % (verify_mode, csv(values)))
    ssllog(" cert_reqs=%#x", ssl_cert_reqs)
    #parse protocol:
    proto = getattr(ssl, "PROTOCOL_%s" % (protocol.upper().replace("V", "v")), None)
    if proto is None:
        values = [k[len("PROTOCOL_"):] for k in dir(ssl) if k.startswith("PROTOCOL_")]
        raise InitException("invalid ssl-protocol '%s', must be one of: %s" % (protocol, csv(values)))
    ssllog(" protocol=%#x", proto)
    #ca_data may be hex encoded:
    ca_data = parse_encoded_bin_data(ca_data)
    ssllog(" cadata=%s", ellipsizer(ca_data))

    kwargs = {
              "server_side"             : server_side,
              "do_handshake_on_connect" : False,
              "suppress_ragged_eofs"    : True,
              }
    #parse ssl-verify-flags as CSV:
    ssl_verify_flags = 0
    for x in verify_flags.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "VERIFY_"+x.upper(), None)
        if v is None:
            raise InitException("invalid ssl verify-flag: %s" % x)
        ssl_verify_flags |= v
    ssllog(" verify_flags=%#x", ssl_verify_flags)
    #parse ssl-options as CSV:
    ssl_options = 0
    for x in options.split(","):
        x = x.strip()
        if not x:
            continue
        v = getattr(ssl, "OP_"+x.upper(), None)
        if v is None:
            raise InitException("invalid ssl option: %s" % x)
        ssl_options |= v
    ssllog(" options=%#x", ssl_options)

    context = ssl.SSLContext(proto)
    context.set_ciphers(ciphers)
    context.verify_mode = ssl_cert_reqs
    context.verify_flags = ssl_verify_flags
    context.options = ssl_options
    ssllog(" cert=%s, key=%s", cert, key)
    if cert:
        if cert=="auto":
            #try to locate the cert file from known locations
            cert = find_ssl_cert()
            if not cert:
                raise InitException("failed to automatically locate an SSL certificate to use")
        SSL_KEY_PASSWORD = os.environ.get("XPRA_SSL_KEY_PASSWORD")
        ssllog("context.load_cert_chain%s", (cert or None, key or None, SSL_KEY_PASSWORD))
        try:
            context.load_cert_chain(certfile=cert or None, keyfile=key or None, password=SSL_KEY_PASSWORD)
        except ssl.SSLError as e:
            ssllog("load_cert_chain", exc_info=True)
            raise InitException("SSL error, failed to load certificate chain: %s" % e) from e
    if ssl_cert_reqs!=ssl.CERT_NONE:
        if server_side:
            purpose = ssl.Purpose.CLIENT_AUTH   #@UndefinedVariable
        else:
            purpose = ssl.Purpose.SERVER_AUTH   #@UndefinedVariable
            context.check_hostname = check_hostname
            ssllog(" check_hostname=%s, server_hostname=%s", check_hostname, server_hostname)
            if context.check_hostname:
                if not server_hostname:
                    raise InitException("ssl error: check-hostname is set but server-hostname is not")
                kwargs["server_hostname"] = server_hostname
        ssllog(" load_default_certs(%s)", purpose)
        context.load_default_certs(purpose)

        if not ca_certs or ca_certs.lower()=="default":
            ssllog(" using default certs")
            #load_default_certs already calls set_default_verify_paths()
        elif not os.path.exists(ca_certs):
            raise InitException("invalid ssl-ca-certs file or directory: %s" % ca_certs)
        elif os.path.isdir(ca_certs):
            ssllog(" loading ca certs from directory '%s'", ca_certs)
            context.load_verify_locations(capath=ca_certs)
        else:
            ssllog(" loading ca certs from file '%s'", ca_certs)
            assert os.path.isfile(ca_certs), "'%s' is not a valid ca file" % ca_certs
            context.load_verify_locations(cafile=ca_certs)
        #handle cadata:
        if ca_data:
            #PITA: because of a bug in the ssl module, we can't pass cadata,
            #so we use a temporary file instead:
            import tempfile
            with tempfile.NamedTemporaryFile(prefix='cadata') as f:
                ssllog(" loading cadata '%s'", ellipsizer(ca_data))
                ssllog(" using temporary file '%s'", f.name)
                f.file.write(ca_data)
                f.file.flush()
                context.load_verify_locations(cafile=f.name)
    elif check_hostname and not server_side:
        ssllog("cannot check hostname client side with verify mode %s", verify_mode)
    return context, kwargs

def do_wrap_socket(tcp_socket, context, **kwargs):
    wrap_socket = context.wrap_socket
    assert tcp_socket
    from xpra.log import Logger
    ssllog = Logger("ssl")
    ssllog("do_wrap_socket(%s, %s)", tcp_socket, context)
    import ssl
    if WIN32:
        #on win32, setting the tcp socket to blocking doesn't work?
        #we still hit the following errors that we need to retry:
        from xpra.net import bytestreams
        bytestreams.CAN_RETRY_EXCEPTIONS = (ssl.SSLWantReadError, ssl.SSLWantWriteError)
    else:
        tcp_socket.setblocking(True)
    try:
        ssl_sock = wrap_socket(tcp_socket, **kwargs)
    except Exception as e:
        ssllog.debug("wrap_socket(%s, %s)", tcp_socket, kwargs, exc_info=True)
        SSLEOFError = getattr(ssl, "SSLEOFError", None)
        if SSLEOFError and isinstance(e, SSLEOFError):
            return None
        raise InitExit(EXIT_SSL_FAILURE, "Cannot wrap socket %s: %s" % (tcp_socket, e)) from None
    return ssl_sock


def ssl_retry(e, ssl_ca_certs):
    SSL_RETRY = envbool("XPRA_SSL_RETRY", True)
    if not SSL_RETRY:
        return None
    if not isinstance(e, SSLVerifyFailure):
        return None
    #we may be able to ask the user if we wants to accept this certificate
    from xpra.log import Logger
    ssllog = Logger("ssl")
    verify_code = e.verify_code
    ssl_sock = e.ssl_sock
    msg = str(e)
    del e
    addr = ssl_sock.getpeername()
    port = addr[-1]
    server_hostname = ssl_sock.server_hostname
    if verify_code not in (SSL_VERIFY_SELF_SIGNED, SSL_VERIFY_WRONG_HOST, SSL_VERIFY_IP_MISMATCH):
        ssllog("ssl_retry: %s not handled here", SSL_VERIFY_CODES.get(verify_code, verify_code))
        return None
    if not server_hostname:
        ssllog("ssl_retry: not server hostname")
        return None
    ssllog("ssl_retry: server_hostname=%s, ssl verify_code=%s (%i)",
           server_hostname, SSL_VERIFY_CODES.get(verify_code, verify_code), verify_code)
    from xpra.platform.paths import get_ssl_hosts_config_dirs
    from xpra.scripts.pinentry_wrapper import get_pinentry_command, run_pinentry_confirm
    host_dirname = std(server_hostname, extras="-.:#_")+":%i" % port
    #self-signed cert:
    if verify_code==SSL_VERIFY_SELF_SIGNED:
        if ssl_ca_certs not in ("", "default"):
            ssllog("self-signed cert does not match %r", ssl_ca_certs)
            return None
        #perhaps we already have the certificate for this hostname
        dirs = get_ssl_hosts_config_dirs()
        host_dirs = [os.path.join(osexpand(d), host_dirname) for d in dirs]
        cert_filename = "cert.pem"
        ssllog("looking for %s in %s", cert_filename, host_dirs)
        for d in host_dirs:
            f = os.path.join(d, cert_filename)
            if os.path.exists(f):
                ssllog("found certificate for %s: %s", server_hostname, f)
                ssllog("retrying")
                return {"ssl_ca_certs" : f}
        #ask the user if he wants to accept this certificate:
        pinentry_cmd = get_pinentry_command()
        if not pinentry_cmd:
            ssllog("no pinentry command, cannot prompt user")
            return None
        #download the certificate data
        import ssl
        try:
            cert_data = ssl.get_server_certificate(addr)
        except ssl.SSLError:
            cert_data = None
        if not cert_data:
            ssllog("failed to get server certificate from %s", addr)
            return None
        ssllog("ssl cert data for %s: %s", addr, ellipsizer(cert_data))
        #ask the user if he wants to accept this certificate:
        title = "SSL Certificate Verification Failure"
        prompt = "%0A".join((
            msg,
            "",
            "Do you want to accept this certificate?",
            ))
        r = run_pinentry_confirm(pinentry_cmd, title, prompt)
        ssllog("run_pinentry_confirm(..) returned %r", r)
        if r!="OK":
            return None
        #if there is an existing host config dir, try to use it:
        for d in [x for x in host_dirs if os.path.exists(x)]:
            try:
                filename = os.path.join(d, cert_filename)
                with open(filename, "wb") as f:
                    f.write(cert_data.encode("latin1"))
                return {"ssl_ca_certs" : f}
            except OSError:
                ssllog("failed to save cert data to %r", filename, exc_info=True)
        #try to create a host config dir:
        for d in host_dirs:
            folders = os.path.normpath(d).split(os.sep)
            #we have to be careful and create the 'ssl' dir with 0o700 permissions
            #but any directory above that can use 0o755
            try:
                ssl_dir_index = len(folders)-1
                while ssl_dir_index>0 and folders[ssl_dir_index]!="ssl":
                    ssl_dir_index -= 1
                if ssl_dir_index>1:
                    parent = os.path.join(*folders[:ssl_dir_index-1])
                    ssl_dir = os.path.join(*folders[:ssl_dir_index])
                    os.makedirs(parent, exist_ok=True)
                    os.makedirs(ssl_dir, mode=0o700, exist_ok=True)
                os.makedirs(d, mode=0o700)
                filename = os.path.join(d, cert_filename)
                ssllog("saving certificate to %r", filename)
                with open(filename, "wb") as f:
                    f.write(cert_data.encode("latin1"))
                ssllog("retrying")
                return {"ssl_ca_certs" : f}
            except OSError:
                ssllog("failed to save cert data to %r", d, exc_info=True)
        ssllog.warn("Warning: failed to save certificate data")
        return None
    if verify_code in (SSL_VERIFY_WRONG_HOST, SSL_VERIFY_IP_MISMATCH):
        #ask the user if he wants to skip verifying the host
        pinentry_cmd = get_pinentry_command()
        if not pinentry_cmd:
            return None
        title = "SSL Certificate Verification Failure"
        prompt = "%0A".join((
            msg,
            "",
            "Do you want to connect anyway?",
            ))
        r = run_pinentry_confirm(pinentry_cmd, title, prompt)
        ssllog("run_pinentry_confirm(..) returned %r", r)
        if r=="OK":
            return {"ssl_check_hostname" : False}
    return None


def socket_connect(host, port, timeout=SOCKET_TIMEOUT):
    socktype = socket.SOCK_STREAM
    family = 0  #0 means any
    try:
        addrinfo = socket.getaddrinfo(host, port, family, socktype)
    except Exception as e:
        raise InitException("cannot get %s address for %s: %s" % ({
            socket.AF_INET6 : "IPv6",
            socket.AF_INET  : "IPv4",
            0               : "any",
            }.get(family, ""), (host, port), e)) from None
    log = get_network_logger()
    log("socket_connect%s addrinfo=%s", (host, port), addrinfo)
    #try each one:
    for addr in addrinfo:
        sockaddr = addr[-1]
        family = addr[0]
        sock = socket.socket(family, socktype)
        sock.settimeout(timeout)
        try:
            log("socket.connect(%s)", sockaddr)
            sock.connect(sockaddr)
            sock.settimeout(None)
            return sock
        except Exception as e:
            log("failed to connect using %s%s for %s", sock.connect, sockaddr, addr, exc_info=True)
            noerr(sock.close)
    return None
