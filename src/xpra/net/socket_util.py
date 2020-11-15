# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import socket
from time import sleep

from xpra.scripts.config import InitException, InitExit, TRUE_OPTIONS
from xpra.exit_codes import (
    EXIT_SSL_FAILURE, EXIT_SSL_CERTIFICATE_VERIFY_FAILURE,
    EXIT_SERVER_ALREADY_EXISTS, EXIT_SOCKET_CREATION_ERROR,
    )
from xpra.net.bytestreams import set_socket_timeout
from xpra.os_util import (
    hexstr, bytestostr,
    getuid, get_username_for_uid, get_groups, get_group_id,
    path_permission_info, monotonic_time, umask_context, WIN32, OSX, POSIX,
    )
from xpra.util import (
    envint, envbool, csv, parse_simple_dict,
    ellipsizer, repr_ellipsized,
    DEFAULT_PORT,
    )

#what timeout value to use on the socket probe attempt:
WAIT_PROBE_TIMEOUT = envint("XPRA_WAIT_PROBE_TIMEOUT", 6)
GROUP = os.environ.get("XPRA_GROUP", "xpra")
PEEK_TIMEOUT = envint("XPRA_PEEK_TIMEOUT", 1)
PEEK_TIMEOUT_MS = envint("XPRA_PEEK_TIMEOUT_MS", PEEK_TIMEOUT*1000)
PEEK_SIZE = envint("XPRA_PEEK_SIZE", 8192)


network_logger = None
def get_network_logger():
    global network_logger
    if not network_logger:
        from xpra.log import Logger
        network_logger = Logger("network")
    return network_logger


def create_unix_domain_socket(sockpath, socket_permissions=0o600):
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
            log.info("removing socket '%s'", delpath)
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

def add_listen_socket(socktype, sock, info, new_connection_cb, new_udp_connection_cb=None):
    log = get_network_logger()
    log("add_listen_socket(%s, %s, %s, %s, %s)", socktype, sock, info, new_connection_cb, new_udp_connection_cb)
    try:
        #ugly that we have different ways of starting sockets,
        #TODO: abstract this into the socket class
        if socktype=="named-pipe":
            #named pipe listener uses a thread:
            sock.new_connection_cb = new_connection_cb
            sock.start()
            return None
        if socktype=="udp":
            assert new_udp_connection_cb, "UDP sockets cannot be handled here"
            new_udp_connection_cb(sock)
            return None
        from gi.repository import GLib
        sock.listen(5)
        def io_in_cb(sock, flags):
            log("io_in_cb(%s, %s)", sock, flags)
            return new_connection_cb(socktype, sock)
        source = GLib.io_add_watch(sock, GLib.PRIORITY_DEFAULT, GLib.IO_IN, io_in_cb)
        sources = [source]
        def cleanup():
            for source in tuple(sources):
                GLib.source_remove(source)
                sources.remove(source)
        return cleanup
    except Exception as e:
        log("add_listen_socket(%s, %s)", socktype, sock, exc_info=True)
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
    log("peek_connection(%s, %i)", conn, timeout)
    peek_data = b""
    start = monotonic_time()
    elapsed = 0
    set_socket_timeout(conn, PEEK_TIMEOUT_MS*1000)
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
        elapsed = int(1000*(monotonic_time()-start))
        log("peek: elapsed=%s, timeout=%s", elapsed, timeout)
    line1 = b""
    log("socket %s peek: got %i bytes", conn, len(peek_data))
    if peek_data:
        line1 = peek_data.splitlines()[0]
        log("socket peek=%s", ellipsizer(peek_data, limit=512))
        log("socket peek hex=%s", hexstr(peek_data[:128]))
        log("socket peek line1=%s", ellipsizer(line1))
    return peek_data, line1


def create_sockets(opts, error_cb):
    log = get_network_logger()

    bind_tcp = parse_bind_ip(opts.bind_tcp)
    bind_udp = parse_bind_ip(opts.bind_udp)
    bind_ssl = parse_bind_ip(opts.bind_ssl, 443)
    bind_ssh = parse_bind_ip(opts.bind_ssh, 22)
    bind_ws  = parse_bind_ip(opts.bind_ws, 80)
    bind_wss = parse_bind_ip(opts.bind_wss, 443)
    bind_rfb = parse_bind_ip(opts.bind_rfb, 5900)
    bind_vsock = parse_bind_vsock(opts.bind_vsock)

    sockets = {}

    min_port = int(opts.min_port)
    def add_tcp_socket(socktype, host_str, iport, options):
        if iport!=0 and iport<min_port:
            error_cb("invalid %s port number %i (minimum value is %i)" % (socktype, iport, min_port))
        for host in hosts(host_str):
            sock = setup_tcp_socket(host, iport, socktype)
            host, iport = sock[2]
            sockets[sock] = options
    def add_udp_socket(socktype, host_str, iport, options):
        if iport!=0 and iport<min_port:
            error_cb("invalid %s port number %i (minimum value is %i)" % (socktype, iport, min_port))
        for host in hosts(host_str):
            sock = setup_udp_socket(host, iport, socktype)
            host, iport = sock[2]
            sockets[sock] = options
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
            add_tcp_socket(socktype, host, iport, options)
    log("setting up UDP sockets: %s", csv(bind_udp.items()))
    for (host, iport), options in bind_udp.items():
        add_udp_socket("udp", host, iport, options)
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

def create_udp_socket(host, iport):
    if host.find(":")<0:
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sockaddr = (host, iport)
    else:
        assert socket.has_ipv6, "specified an IPv6 address but this is not supported"
        res = socket.getaddrinfo(host, iport, socket.AF_INET6, socket.SOCK_DGRAM)
        listener = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sockaddr = res[0][-1]
    listener.bind(sockaddr)
    return listener

def setup_udp_socket(host, iport, socktype="udp"):
    log = get_network_logger()
    try:
        udp_socket = create_udp_socket(host, iport)
    except Exception as e:
        log("create_udp_socket%s", (host, iport), exc_info=True)
        raise InitExit(EXIT_SOCKET_CREATION_ERROR,
                       "failed to setup %s socket on %s:%s %s" % (socktype, host, iport, e))
    def cleanup_udp_socket():
        log.info("closing %s socket %s:%s", socktype, host, iport)
        try:
            udp_socket.close()
        except OSError:
            pass
    if iport==0:
        iport = udp_socket.getsockname()[1]
        log.info("allocated UDP port %i for %s", iport, host)
    log("%s: %s:%s : %s", socktype, host, iport, socket)
    log.info("created UDP socket %s:%s", host, iport)
    return socktype, udp_socket, (host, iport), cleanup_udp_socket


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
                except:
                    raise InitException("invalid port number: %s" % port)
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
        from xpra.scripts.main import parse_vsock
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
        log.info("closing sd listen socket %s", addr)
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
    if WIN32:
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
    if display_name is not None:
        display_name = normalize_local_display_name(display_name)
    log = get_network_logger()
    defs = {}
    try:
        sockpaths = {}
        log("setup_local_sockets: bind=%s", bind)
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
                if os.path.isabs(sockpath):
                    pass
                elif sockpath.endswith("/") or (os.path.exists(sockpath) and os.path.isdir(sockpath)):
                    assert display_name is not None
                    sockpath = os.path.abspath(sockpath)
                    if not os.path.exists(sockpath):
                        os.makedirs(sockpath)
                    sockpath = norm_makepath(sockpath, display_name)
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
        #create listeners:
        if WIN32:
            from xpra.platform.win32.namedpipes.listener import NamedPipeListener
            for sockpath, options in sockpaths.items():
                npl = NamedPipeListener(sockpath)
                log.info("created named pipe '%s'", sockpath)
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
                    if getuid()==0 and d=="/var/run/xpra" or d=="/run/xpra":
                        #this is normally done by tmpfiles.d,
                        #but we may need to do it ourselves in some cases:
                        kwargs = {"mode"  : 0o775}
                        xpra_gid = get_group_id("xpra")
                        if xpra_gid>0:
                            kwargs["gid"] = xpra_gid
                    log("creating sockdir=%s, kwargs=%s" % (d, kwargs))
                    dotxpra.mksockdir(d, **kwargs)
                except Exception as e:
                    log.warn("Warning: failed to create socket directory '%s'", d)
                    log.warn(" %s", e)
                    del e
            #wait for all the unknown ones:
            log("sockets in unknown state: %s", unknown)
            if unknown:
                #re-probe them using threads so we can do them in parallel:
                from xpra.make_thread import start_thread
                threads = []
                def timeout_probe(sockpath):
                    #we need a loop because "DEAD" sockets may return immediately
                    #(ie: when the server is starting up)
                    start = monotonic_time()
                    while monotonic_time()-start<WAIT_PROBE_TIMEOUT:
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
            except Exception as e:
                log.error("Error cleaning up socket %s:", sock)
                log.error(" %s", e)
                del e
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
        if POSIX and (sperms & 0o40):
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


def guess_header_protocol(v):
    c = int(v[0])
    s = bytestostr(v)
    get_network_logger().debug("guess_header_protocol(%r) first char=%#x", repr_ellipsized(s), c)
    if c==0x16:
        return "ssl", "SSL packet?"
    if s[:4]=="SSH-":
        return "ssh", "SSH packet"
    if len(s)>=3 and s.split(" ")[0] in ("GET", "POST"):
        return "HTTP", "HTTP %s request" % s.split(" ")[0]
    return None, "character %#x, not an xpra client?" % c


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
        PREFER_ZEROCONF = envbool("XPRA_PREFER_ZEROCONF", False) or WIN32 or OSX
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

def ssl_wrap_socket(sock, **kwargs):
    fn = get_ssl_wrap_socket_fn(**kwargs)
    return fn(sock)

def get_ssl_wrap_socket_fn(cert=None, key=None, ca_certs=None, ca_data=None,
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
    ssllog("get_ssl_wrap_socket_fn%s", (cert, key, ca_certs, ca_data,
                                    protocol,
                                    client_verify_mode, server_verify_mode, verify_flags,
                                    check_hostname, server_hostname,
                                    options, ciphers,
                                    server_side))
    import ssl
    ssllog(" verify_mode(%s)=%s", server_side, verify_mode)
    #ca-certs:
    if ca_certs=="default":
        ca_certs = None
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
    if ca_data:
        import binascii
        try:
            ca_data = binascii.unhexlify(ca_data)
        except (TypeError, binascii.Error):
            import base64
            ca_data = base64.b64decode(ca_data)
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
        SSL_KEY_PASSWORD = os.environ.get("XPRA_SSL_KEY_PASSWORD")
        context.load_cert_chain(certfile=cert or None, keyfile=key or None, password=SSL_KEY_PASSWORD)
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
    wrap_socket = context.wrap_socket
    def do_wrap_socket(tcp_socket):
        assert tcp_socket
        ssllog("do_wrap_socket(%s)", tcp_socket)
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
            raise InitExit(EXIT_SSL_FAILURE, "Cannot wrap socket %s: %s" % (tcp_socket, e))
        if not server_side:
            try:
                ssl_sock.do_handshake(True)
            except Exception as e:
                ssllog.debug("do_handshake", exc_info=True)
                SSLEOFError = getattr(ssl, "SSLEOFError", None)
                if SSLEOFError and isinstance(e, SSLEOFError):
                    return None
                status = EXIT_SSL_FAILURE
                SSLCertVerificationError = getattr(ssl, "SSLCertVerificationError", None)
                if SSLCertVerificationError and isinstance(e, SSLCertVerificationError):
                    try:
                        msg = e.args[1].split(":", 2)[2]
                    except (ValueError, IndexError):
                        msg = str(e)
                    status = EXIT_SSL_CERTIFICATE_VERIFY_FAILURE
                    #ssllog.warn("host failed SSL verification: %s", msg)
                else:
                    msg = str(e)
                raise InitExit(status, "SSL handshake failed: %s" % msg)
        return ssl_sock
    return do_wrap_socket

