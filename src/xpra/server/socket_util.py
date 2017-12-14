# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import socket

from xpra.scripts.config import InitException
from xpra.os_util import getuid, get_username_for_uid, get_groups, get_group_id, path_permission_info, monotonic_time, WIN32, OSX, POSIX
from xpra.util import envint, envbool, csv, DEFAULT_PORT
from xpra.platform.dotxpra import DotXpra, norm_makepath


#what timeout value to use on the socket probe attempt:
WAIT_PROBE_TIMEOUT = envint("XPRA_WAIT_PROBE_TIMEOUT", 6)


def add_cleanup(f):
    from xpra.scripts import server
    server.add_cleanup(f)


network_logger = None
def get_network_logger():
    global network_logger
    if not network_logger:
        from xpra.log import Logger
        network_logger = Logger("network")
    return network_logger


def create_unix_domain_socket(sockpath, mmap_group=False, socket_permissions="600"):
    if mmap_group:
        #when using the mmap group option, use '660'
        umask = 0o117
    else:
        #parse octal mode given as config option:
        try:
            if type(socket_permissions)==int:
                sperms = socket_permissions
            else:
                #assume octal string:
                sperms = int(socket_permissions, 8)
            assert sperms>=0 and sperms<=0o777
        except ValueError:
            raise ValueError("invalid socket permissions (must be an octal number): '%s'" % socket_permissions)
        #now convert this to a umask!
        umask = 0o777-sperms
    listener = socket.socket(socket.AF_UNIX)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #bind the socket, using umask to set the correct permissions
    orig_umask = os.umask(umask)
    try:
        listener.bind(sockpath)
    finally:
        os.umask(orig_umask)
    try:
        inode = os.stat(sockpath).st_ino
    except:
        inode = -1
    #set to the "xpra" group if we are a member of it, or if running as root:
    uid = getuid()
    username = get_username_for_uid(uid)
    groups = get_groups(username)
    if uid==0 or "xpra" in groups:
        group_id = get_group_id("xpra")
        if group_id>=0:
            try:
                os.lchown(sockpath, -1, group_id)
            except Exception as e:
                log = get_network_logger()
                log.warn("Warning: failed to set 'xpra' group ownership")
                log.warn(" on socket '%s':", sockpath)
                log.warn(" %s", e)
            #don't know why this doesn't work:
            #os.fchown(listener.fileno(), -1, group_id)
    def cleanup_socket():
        log = get_network_logger()
        try:
            cur_inode = os.stat(sockpath).st_ino
        except:
            log.info("socket '%s' already deleted", sockpath)
            return
        delpath = sockpath
        log("cleanup_socket '%s', original inode=%s, new inode=%s", sockpath, inode, cur_inode)
        if cur_inode==inode:
            log.info("removing socket %s", delpath)
            try:
                os.unlink(delpath)
            except:
                pass
    return listener, cleanup_socket

def has_dual_stack():
    """
        Return True if kernel allows creating a socket which is able to
        listen for both IPv4 and IPv6 connections.
        If *sock* is provided the check is made against it.
    """
    try:
        socket.AF_INET6
        socket.IPPROTO_IPV6
        socket.IPV6_V6ONLY
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

def create_tcp_socket(host, iport):
    from xpra.net.bytestreams import TCP_NODELAY
    if host.find(":")<0:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockaddr = (host, iport)
    else:
        assert socket.has_ipv6, "specified an IPv6 address but this is not supported"
        res = socket.getaddrinfo(host, iport, socket.AF_INET6, socket.SOCK_STREAM, 0, socket.SOL_TCP)
        log = get_network_logger()
        log("socket.getaddrinfo(%s, %s, AF_INET6, SOCK_STREAM, 0, SOL_TCP)=%s", host, iport, res)
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sockaddr = res[0][-1]
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, TCP_NODELAY)
    listener.bind(sockaddr)
    return listener

def setup_tcp_socket(host, iport, socktype="tcp"):
    log = get_network_logger()
    try:
        tcp_socket = create_tcp_socket(host, iport)
    except Exception as e:
        log("create_tcp_socket%s", (host, iport), exc_info=True)
        raise InitException("failed to setup %s socket on %s:%s %s" % (socktype, host, iport, e))
    def cleanup_tcp_socket():
        log.info("closing %s socket %s:%s", socktype.lower(), host, iport)
        try:
            tcp_socket.close()
        except:
            pass
    add_cleanup(cleanup_tcp_socket)
    log("%s: %s:%s : %s", socktype, host, iport, socket)
    return socktype, tcp_socket, (host, iport)

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
        raise InitException("failed to setup %s socket on %s:%s %s" % (socktype, host, iport, e))
    def cleanup_udp_socket():
        log.info("closing %s socket %s:%s", socktype, host, iport)
        try:
            udp_socket.close()
        except:
            pass
    add_cleanup(cleanup_udp_socket)
    log("%s: %s:%s : %s", socktype, host, iport, socket)
    return socktype, udp_socket, (host, iport)


def parse_bind_ip(bind_ip, default_port=DEFAULT_PORT):
    ip_sockets = set()
    if bind_ip:
        for spec in bind_ip:
            if ":" not in spec:
                raise InitException("port must be specified as [HOST]:PORT")
            host, port = spec.rsplit(":", 1)
            if host == "":
                host = "127.0.0.1"
            if not port:
                iport = default_port
            else:
                try:
                    iport = int(port)
                    assert iport>0 and iport<2**16
                except:
                    raise InitException("invalid port number: %s" % port)
            ip_sockets.add((host, iport))
    return ip_sockets

def setup_vsock_socket(cid, iport):
    log = get_network_logger()
    try:
        from xpra.net.vsock import bind_vsocket     #@UnresolvedImport
        vsock_socket = bind_vsocket(cid=cid, port=iport)
    except Exception as e:
        raise InitException("failed to setup vsock socket on %s:%s %s" % (cid, iport, e))
    def cleanup_vsock_socket():
        log.info("closing vsock socket %s:%s", cid, iport)
        try:
            vsock_socket.close()
        except:
            pass
    add_cleanup(cleanup_vsock_socket)
    return "vsock", vsock_socket, (cid, iport)

def parse_bind_vsock(bind_vsock):
    vsock_sockets = set()
    if bind_vsock:
        from xpra.scripts.main import parse_vsock
        for spec in bind_vsock:
            vsock_sockets.add(parse_vsock(spec))
    return vsock_sockets


def normalize_local_display_name(local_display_name):
    pos = local_display_name.find(":")
    if pos<0:
        after_sc = local_display_name
        local_display_name = ":" + local_display_name
    else:
        after_sc = local_display_name[pos+1:]
    #we used to strip the screen from the display string, ie: ":0.0" -> ":0"
    #but now we allow it.. (untested!)
    for char in after_sc:
        assert char in "0123456789.", "invalid character in display name '%s': %s" % (local_display_name, char)
    return local_display_name


def setup_local_sockets(bind, socket_dir, socket_dirs, display_name, clobber, mmap_group=False, socket_permissions="600", username="", uid=0, gid=0):
    if not bind:
        return []
    if not socket_dir and (not socket_dirs or (len(socket_dirs)==1 and not socket_dirs[0])):
        raise InitException("at least one socket directory must be set to use unix domain sockets")
    dotxpra = DotXpra(socket_dir or socket_dirs[0], socket_dirs, username, uid, gid)
    display_name = normalize_local_display_name(display_name)
    log = get_network_logger()
    defs = []
    try:
        sockpaths = []
        log("setup_local_sockets: bind=%s", bind)
        for b in bind:
            sockpath = b
            if b=="none" or b=="":
                continue
            elif b=="auto":
                sockpaths += dotxpra.norm_socket_paths(display_name)
                log("sockpaths(%s)=%s (uid=%i, gid=%i)", display_name, sockpaths, uid, gid)
            else:
                sockpath = dotxpra.osexpand(b)
                if b.endswith("/") or (os.path.exists(sockpath) and os.path.isdir(sockpath)):
                    sockpath = os.path.abspath(sockpath)
                    if not os.path.exists(sockpath):
                        os.makedirs(sockpath)
                    sockpath = norm_makepath(sockpath, display_name)
                elif os.path.isabs(b):
                    sockpath = b
                else:
                    sockpath = dotxpra.socket_path(b)
                sockpaths += [sockpath]
            assert sockpaths, "no socket paths to try for %s" % b
        #expand and remove duplicate paths:
        tmp = []
        for tsp in sockpaths:
            sockpath = dotxpra.osexpand(tsp)
            if sockpath in tmp:
                log.warn("Warning: skipping duplicate bind path %s", sockpath)
                continue
            tmp.append(sockpath)
        sockpaths = tmp
        #create listeners:
        if WIN32:
            from xpra.platform.win32.namedpipes.listener import NamedPipeListener
            for sockpath in sockpaths:
                npl = NamedPipeListener(sockpath)
                log.info("created named pipe: %s", sockpath)
                defs.append((("named-pipe", npl, sockpath), npl.stop))
        else:
            def checkstate(sockpath, state):
                if state not in (DotXpra.DEAD, DotXpra.UNKNOWN):
                    if state==DotXpra.INACCESSIBLE:
                        raise InitException("An xpra server is already running at %s\n" % (sockpath,))
                    raise InitException("You already have an xpra server running at %s\n"
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
                from time import sleep
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
            #now we can re-check quickly:
            #(they should all be DEAD or UNKNOWN):
            for sockpath in sockpaths:
                state = dotxpra.get_server_state(sockpath, 1)
                log("state(%s)=%s", sockpath, state)
                checkstate(sockpath, state)
                try:
                    if os.path.exists(sockpath):
                        os.unlink(sockpath)
                except:
                    pass
            #now try to create all the sockets:
            for sockpath in sockpaths:
                #create it:
                try:
                    sock, cleanup_socket = create_unix_domain_socket(sockpath, mmap_group, socket_permissions)
                    log.info("created unix domain socket: %s", sockpath)
                    defs.append((("unix-domain", sock, sockpath), cleanup_socket))
                except Exception as e:
                    handle_socket_error(sockpath, e)
                    del e
    except:
        for sock, cleanup_socket in defs:
            try:
                cleanup_socket()
            except Exception as e:
                log.error("Error cleaning up socket %s:", sock)
                log.error(" %s", e)
                del e
        defs = []
        raise
    return defs

def handle_socket_error(sockpath, e):
    log = get_network_logger()
    log("socket creation error", exc_info=True)
    if sockpath.startswith("/var/run/xpra") or sockpath.startswith("/run/xpra"):
        log.warn("Warning: cannot create socket '%s'", sockpath)
        log.warn(" %s", e)
        dirname = sockpath[:sockpath.find("xpra")+len("xpra")]
        if not os.path.exists(dirname):
            log.warn(" %s does not exist", dirname)
        if POSIX:
            uid = getuid()
            username = get_username_for_uid(uid)
            groups = get_groups(username)
            log.warn(" user '%s' is a member of groups: %s", username, csv(groups) or "no groups!")
            if "xpra" not in groups:
                log.warn("  missing 'xpra' group membership?")
            for x in path_permission_info(dirname):
                log.warn("  %s", x)
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
        raise InitException("failed to create socket %s" % sockpath)


#warn just once:
MDNS_WARNING = False
def mdns_publish(display_name, mode, listen_on, text_dict={}):
    global MDNS_WARNING
    if MDNS_WARNING is True:
        return
    PREFER_PYBONJOUR = envbool("XPRA_PREFER_PYBONJOUR", False) or WIN32 or OSX
    try:
        from xpra.net import mdns
        assert mdns
        if PREFER_PYBONJOUR:
            from xpra.net.mdns.pybonjour_publisher import BonjourPublishers as MDNSPublishers, get_interface_index
        else:
            from xpra.net.mdns.avahi_publisher import AvahiPublishers as MDNSPublishers, get_interface_index
    except ImportError as e:
        MDNS_WARNING = True
        log = get_network_logger()
        log("mdns import failure", exc_info=True)
        log.warn("Warning: failed to load the mdns %s publisher:", ["avahi", "pybonjour"][PREFER_PYBONJOUR])
        log.warn(" %s", e)
        log.warn(" either fix your installation or use the 'mdns=no' option")
        return
    d = text_dict.copy()
    d["mode"] = mode
    #ensure we don't have duplicate interfaces:
    f_listen_on = {}
    for host, port in listen_on:
        f_listen_on[get_interface_index(host)] = (host, port)
    try:
        name = socket.gethostname()
    except:
        name = "Xpra"
    if display_name and not (OSX or WIN32):
        name += " %s" % display_name
    if mode!="tcp":
        name += " (%s)" % mode
    ap = MDNSPublishers(f_listen_on.values(), name, text_dict=d)
    from xpra.scripts.server import add_when_ready, add_cleanup
    add_when_ready(ap.start)
    add_cleanup(ap.stop)
