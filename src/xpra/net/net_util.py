#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

import socket
import sys

from xpra.log import Logger
log = Logger("network", "util")


has_netifaces = True
netifaces_version = None
try:
	import netifaces				#@UnresolvedImport
	log("netifaces loaded sucessfully")
	netifaces_version = netifaces.version		#@UndefinedVariable
except:
	has_netifaces = False
	log.warn("python netifaces package is missing")
iface_ipmasks = {}
bind_IPs = None


def get_free_tcp_port():
	s = socket.socket()
	s.bind(('', 0))
	port = s.getsockname()[1]
	s.close()
	return port


def get_interfaces():
	if not has_netifaces:
		return	[]
	return	netifaces.interfaces()			#@UndefinedVariable

def get_gateways():
	if not has_netifaces:
		return	{}
	#versions older than 0.10.5 can crash when calling gateways()
	#https://bitbucket.org/al45tair/netifaces/issues/15/gateways-function-crash-segmentation-fault
	if netifaces.version<'0.10.5':			#@UndefinedVariable
		return {}
	try:
		d =	netifaces.gateways()			#@UndefinedVariable
		AF_NAMES = {}
		for k in dir(netifaces):
			if k.startswith("AF_"):
				v = getattr(netifaces, k)
				AF_NAMES[v] = k[3:]
		gateways = {}
		for family, gws in d.items():
			if family=="default":
				continue
			gateways[AF_NAMES.get(family, family)] = gws
		return gateways
	except:
		log("get_gateways() failed", exc_info=True)
		return {}

def get_bind_IPs():
	global bind_IPs
	if not bind_IPs:
		if has_netifaces:
			bind_IPs = do_get_bind_IPs()
		else:
			bind_IPs = ["127.0.0.1"]
	return	bind_IPs

def do_get_bind_IPs():
	global iface_ipmasks
	ips = []
	ifaces = netifaces.interfaces()			#@UndefinedVariable
	log("ifaces=%s", ifaces)
	for iface in ifaces:
		if_ipmasks = []
		try:
			ipmasks = do_get_bind_ifacemask(iface)
			for ipmask in ipmasks:
				(ip,_) = ipmask
				if ip not in ips:
					ips.append(ip)
				if ipmask not in if_ipmasks:
					if_ipmasks.append(ipmask)
		except Exception as e:
			log("do_get_bind_IPs()", exc_info=True)
			log.error("Error parsing network interface '%s':", iface)
			log.error(" %s", iface, e)
		iface_ipmasks[iface] = if_ipmasks
	log("do_get_bind_IPs()=%s", ips)
	return ips

def do_get_bind_ifacemask(iface):
	ipmasks = []
	address_types = netifaces.ifaddresses(iface)	#@UndefinedVariable
	for addresses in address_types.values():
		for address in addresses:
			if 'netmask' in address and 'addr' in address:
				addr = address['addr']
				mask = address['netmask']
				if addr!= '::1' and addr != '0.0.0.0' and addr.find("%")<0:
					try:
						socket.inet_aton(addr)
						ipmasks.append((addr,mask))
					except Exception as e:
						log.error("do_get_bind_ifacemask(%s) error on %s", iface, addr, e)
	log("do_get_bind_ifacemask(%s)=%s", iface, ipmasks)
	return ipmasks

def get_iface(ip):
	log("get_iface(%s)", ip)
	if not ip:
		return	None
	if ip.find(":")>=0:
		#ipv6?
		return None
	if any(x for x in ip if (".:0123456789").find(x)<0):
		#extra characters, assume this is a hostname:
		try:
			v = socket.getaddrinfo(ip, None)
			assert len(v)>0
		except Exception as e:
			log.error("Error: cannot revolve '%s'", ip)
			return None
		for i, x in enumerate(v):
			family, socktype, proto, canonname, sockaddr = x
			log("get_iface(%s) [%i]=%s", ip, i, (family, socktype, proto, canonname, sockaddr))
			if family==socket.AF_INET:
				break
		log("get_iface(%s) sockaddr=%s", ip, sockaddr)
		ip = sockaddr[0]

	ip_parts = ip.split(".")
	if len(ip_parts)!=4:
		return	None

	best_match = None
	get_bind_IPs()
	for (iface, ipmasks) in iface_ipmasks.items():
		for (test_ip,mask) in ipmasks:
			if test_ip == ip:
				#exact match
				log("get_iface(%s)=%s", iface, ip)
				return	iface
			test_ip_parts = test_ip.split(".")
			mask_parts = mask.split(".")
			if len(test_ip_parts)!=4 or len(mask_parts)!=4:
				log.error("incorrect ip or mask: %s/%s", test_ip, mask)
			match = True
			try:
				for i in [0,1,2,3]:
					mask_part = int(mask_parts[i])
					ip_part = int(ip_parts[i]) & mask_part
					test_ip_part = int(test_ip_parts[i]) & mask_part
					if ip_part!=test_ip_part:
						match = False
						break
				if match:
					best_match = iface
			except Exception as e:
				log.error("error parsing ip (%s) or its mask (%s): %s", test_ip, mask, e)
	log("get_iface(%s)=%s", ip, best_match)
	return	best_match


# Found this recipe here:
# http://code.activestate.com/recipes/442490/
if_nametoindex = None
if_indextoname = None
from xpra.os_util import WIN32, OSX
if not WIN32:
	library = "libc.so.6"
	if OSX:
		library = "/usr/lib/libc.dylib"
	elif sys.platform.startswith("sunos"):
		library = "libsocket.so.1"
	elif sys.platform.startswith("freebsd"):
		library = "/lib/libc.so.7"
	elif sys.platform.startswith("openbsd"):
		library = "libc.so"
	try:
		from ctypes import cdll, CDLL, c_char_p, c_uint, create_string_buffer
		cdll.LoadLibrary(library)
		#<CDLL 'libc.so.6', handle 7fcac419b000 at 7fcac1ab0c10>
		_libc = CDLL(library)
		log("successfully loaded socket C library from %s", library)
	except ImportError as e:
		log.error("library %s not found: %s", library, e)
	except OSError as e:
		log.error("error loading %s: %s", library, e)
	else:
		_libc.if_indextoname.restype = c_char_p
		_libc.if_indextoname.argtypes = [c_uint, c_char_p]
		_libc.if_nametoindex.restype = c_uint
		_libc.if_nametoindex.argtypes = [c_char_p]
		def if_nametoindex(interfaceName):
			return _libc.if_nametoindex(create_string_buffer(interfaceName.encode()))
		def if_indextoname(index):
			s = create_string_buffer(b'\000' * 256)
			return _libc.if_indextoname(c_uint(index), s)

net_sys_config = None
def get_net_sys_config():
	global net_sys_config
	if net_sys_config is None:
		net_sys_config = {}
		if sys.platform.startswith("linux"):
			def stripnl(v):
				return str(v).rstrip("\r").rstrip("\n")
			def addproc(procpath, subsystem, name, conv=stripnl):
				assert name
				try:
					with open(procpath) as f:
						data = f.read()
						subdict = net_sys_config.setdefault(subsystem, {})
						if name.find("/")>0:
							sub, name = name.split("/", 1)
							subdict = subdict.setdefault(sub, {})
						for sub in ("ip", "tcp", "ipfrag", "icmp", "igmp"):
							if name.startswith("%s_" % sub):
								name = name[len(sub)+1:]
								subdict = subdict.setdefault(sub, {})
								break
						subdict[name] = conv(data)
				except Exception as e:
					log("cannot read '%s': %s", procpath, e)
			for k in ("netdev_max_backlog", "optmem_max", "rmem_default", "rmem_max", "wmem_default", "wmem_max", "max_skb_frags",
					"busy_poll", "busy_read", "somaxconn"):
				addproc("/proc/sys/net/core/%s" % k, 	"core", k, int)
			for k in ("default_qdisc", ):
				addproc("/proc/sys/net/core/%s" % k, 	"core", k)
			for k in ("max_dgram_qlen", ):
				addproc("/proc/sys/net/unix/%s" % k, 	"unix", k, int)
			for k in ("ip_forward", "ip_forward_use_pmtu", "tcp_abort_on_overflow", "fwmark_reflect", "tcp_autocorking", "tcp_dsack",
					"tcp_ecn_fallback", "tcp_fack",
					#"tcp_l3mdev_accept",
					"tcp_low_latency", "tcp_no_metrics_save", "tcp_recovery", "tcp_retrans_collapse", "tcp_timestamps",
					"tcp_workaround_signed_windows", "tcp_thin_linear_timeouts", "tcp_thin_dupack", "ip_nonlocal_bind",
					"ip_dynaddr", "ip_early_demux", "icmp_echo_ignore_all", "icmp_echo_ignore_broadcasts",
					):
				addproc("/proc/sys/net/ipv4/%s" % k, 	"ipv4", k, bool)
			for k in ("tcp_allowed_congestion_control", "tcp_available_congestion_control", "tcp_congestion_control", "tcp_early_retrans",
					"tcp_moderate_rcvbuf", "tcp_rfc1337", "tcp_sack", "tcp_slow_start_after_idle", "tcp_stdurg",
					"tcp_syncookies", "tcp_tw_recycle", "tcp_tw_reuse", "tcp_window_scaling",
					"icmp_ignore_bogus_error_responses", "icmp_errors_use_inbound_ifaddr"):
				addproc("/proc/sys/net/ipv4/%s" % k, 	"ipv4", k)
			def parsenums(v):
				return tuple(int(x.strip()) for x in v.split("\t") if len(x.strip())>0)
			for k in ("tcp_mem", "tcp_rmem", "tcp_wmem", "ip_local_port_range", "ip_local_reserved_ports", ):
				addproc("/proc/sys/net/ipv4/%s" % k, 	"ipv4", k, parsenums)
			for k in ("ip_default_ttl", "ip_no_pmtu_disc", "route/min_pmtu",
					"route/mtu_expires", "route/min_adv_mss",
					"ipfrag_high_thresh", "ipfrag_low_thresh", "ipfrag_time", "ipfrag_max_dist",
					"tcp_adv_win_scale", "tcp_app_win", "tcp_base_mss", "tcp_ecn", "tcp_fin_timeout", "tcp_frto",
					"tcp_invalid_ratelimit", "tcp_keepalive_time", "tcp_keepalive_probes", "tcp_keepalive_intvl",
					"tcp_max_orphans", "tcp_max_syn_backlog", "tcp_max_tw_buckets",
					"tcp_min_rtt_wlen", "tcp_mtu_probing", "tcp_probe_interval", "tcp_probe_threshold", "tcp_orphan_retries",
					"tcp_reordering", "tcp_max_reordering", "tcp_retries1", "tcp_retries2", "tcp_synack_retries",
					"tcp_fastopen", "tcp_syn_retries", "tcp_min_tso_segs", "tcp_pacing_ss_ratio",
					"tcp_pacing_ca_ratio", "tcp_tso_win_divisor", "tcp_notsent_lowat",
					"tcp_limit_output_bytes", "tcp_challenge_ack_limit",
					"icmp_ratelimit", "icmp_msgs_per_sec", "icmp_msgs_burst", "icmp_ratemask",
					"igmp_max_memberships", "igmp_max_msf", "igmp_qrv",
					):
				addproc("/proc/sys/net/ipv4/%s" % k, 	"ipv4", k, int)
	return net_sys_config

def get_net_config():
	try:
		from xpra.net.bytestreams import VSOCK_TIMEOUT, SOCKET_TIMEOUT, TCP_NODELAY
		return {
				"vsocket.timeout"	: VSOCK_TIMEOUT,
				"socket.timeout"	: SOCKET_TIMEOUT,
				"tcp.nodelay"		: TCP_NODELAY,
				}
	except:
		return {}

def get_ssl_info():
	try:
		import ssl
	except ImportError as e:
		log("no ssl: %s", e)
		return {}
	protocols = dict((k,getattr(ssl, k)) for k in dir(ssl) if k.startswith("PROTOCOL_"))
	ops = dict((k,getattr(ssl, k)) for k in dir(ssl) if k.startswith("OP_"))
	vers = dict((k,getattr(ssl, k)) for k in dir(ssl) if k.startswith("VERIFY_"))
	info = {
			"protocols"	: protocols,
			"options"	: ops,
			"verify"	: vers,
			}
	for k,name in {
					"HAS_ALPN"				: "alpn",
					"HAS_ECDH"				: "ecdh",
					"HAS_SNI"				: "sni",
					"HAS_NPN"				: "npn",
					"CHANNEL_BINDING_TYPES"	: "channel-binding-types",
					}.items():
		v = getattr(ssl, k, None)
		if v is not None:
			info[name] = v
	for k,name in {
					""			: "version",
					"_INFO"		: "version-info",
					"_NUMBER"	: "version-number",
					}.items():
		v = getattr(ssl, "OPENSSL_VERSION%s" % k, None)
		if v is not None:
			info.setdefault("openssl", {})[name] = v
	return info


def get_network_caps():
    try:
        from xpra.platform.features import MMAP_SUPPORTED
    except:
        MMAP_SUPPORTED = False
    from xpra.net.crypto import get_digests, get_crypto_caps
    from xpra.net.compression import get_enabled_compressors, get_compression_caps
    from xpra.net.packet_encoding import get_enabled_encoders, get_packet_encoding_caps
    caps = {
                "digest"                : get_digests(),
                "compressors"           : get_enabled_compressors(),
                "encoders"              : get_enabled_encoders(),
                "mmap"                  : MMAP_SUPPORTED,
               }
    caps.update(get_crypto_caps())
    caps.update(get_compression_caps())
    caps.update(get_packet_encoding_caps())
    return caps


def get_info():
	log.info("net_util.get_info()")
	i = get_network_caps()
	if has_netifaces:
		i["interfaces"] = get_interfaces()
		i["gateways"] = get_gateways()
	if "ssl" in sys.modules:
		ssli = get_ssl_info()
		ssli[""] = True
		i["ssl"] = ssli
	s = get_net_sys_config()
	if s:
		i["system"] = s
	i["config"] = get_net_config()
	log.info("net_util.get_info()=%s", i)
	return i


def main():
	from xpra.util import print_nested_dict
	from xpra.platform import program_context
	from xpra.log import enable_color
	with program_context("Network-Info", "Network Info"):
		enable_color()
		verbose = "-v" in sys.argv or "--verbose" in sys.argv
		if verbose:
			log.enable_debug()

		print("Network interfaces found:")
		for iface in get_interfaces():
			if if_nametoindex:
				print("* %s (index=%s)" % (iface.ljust(20), if_nametoindex(iface)))
			else:
				print("* %s" % iface)

		def pver(v):
			if type(v) in (tuple, list):
				s = ""
				for i in range(len(v)):
					if i>0:
						#dot seperated numbers
						if type(v[i-1])==int:
							s += "."
						else:
							s += ", "
					s += str(v[i])
				return s
			if type(v)==bytes:
				from xpra.os_util import bytestostr
				v = bytestostr(v)
			if type(v)==str and v.startswith("v"):
				return v[1:]
			return str(v)

		print("Gateways found:")
		print_nested_dict(get_gateways())

		print("")
		print("Protocol Capabilities:")
		from xpra.net.protocol import get_network_caps
		netcaps = get_network_caps()
		netif = {""	: has_netifaces}
		if netifaces_version:
			netif["version"] = netifaces_version
		netcaps["netifaces"] = netif
		print_nested_dict(netcaps)

		print("")
		print("Network Config:")
		print_nested_dict(get_net_config())

		net_sys = get_net_sys_config()
		if net_sys:
			print("")
			print("Network System Config:")
			print_nested_dict(net_sys)

		print("")
		print("SSL:")
		print_nested_dict(get_ssl_info())

		try:
			from xpra.net.crypto import crypto_backend_init, get_crypto_caps
			crypto_backend_init()
			ccaps = get_crypto_caps()
			if ccaps:
				print("")
				print("Crypto Capabilities:")
				print_nested_dict(ccaps)
		except Exception as e:
			print("No Crypto:")
			print(" %s" % e)


if __name__ == "__main__":
	main()
