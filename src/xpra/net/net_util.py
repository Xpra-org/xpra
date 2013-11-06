#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

import socket
import sys

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_NETWORK_DEBUG")


has_netifaces = True
try:
	import netifaces				#@UnresolvedImport
	debug("netifaces loaded sucessfully")
except Exception, e:
	has_netifaces = False
	log.warn("python netifaces package is missing")
iface_ipmasks = {}
bind_IPs = None


def get_interfaces():
	if not has_netifaces:
		return	[]
	return	netifaces.interfaces()

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
	ifaces = netifaces.interfaces()
	debug("ifaces=%s", ifaces)
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
		except Exception, e:
			log.error("error on %s: %s", iface, e)
		iface_ipmasks[iface] = if_ipmasks
	debug("do_get_bind_IPs()=%s", ips)
	return ips

def do_get_bind_ifacemask(iface):
	ipmasks = []
	address_types = netifaces.ifaddresses(iface)
	for addresses in address_types.values():
		for address in addresses:
			if 'netmask' in address and 'addr' in address:
				addr = address['addr']
				mask = address['netmask']
				if addr!= '::1' and addr != '0.0.0.0' and addr.find("%")<0:
					try:
						socket.inet_aton(addr)
						ipmasks.append((addr,mask))
					except Exception, e:
						log.error("do_get_bind_ifacemask(%s) error on %s", iface, addr, e)
	debug("do_get_bind_ifacemask(%s)=%s", iface, ipmasks)
	return ipmasks

def get_iface(ip):
	if not ip:
		return	None
	if ip.find(":")>=0:
		#ipv6?
		return None
	ip_parts = ip.split(".")
	if len(ip_parts)!=4:
		log.error("invalid IPv4! (%d parts)", len(ip_parts))
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
			except Exception, e:
				log.error("error parsing ip (%s) or its mask (%s): %s", test_ip, mask, e)
	debug("get_iface(%s)=%s", ip, best_match)
	return	best_match


# Found this recipe here:
# http://code.activestate.com/recipes/442490/
if_nametoindex = None
if_indextoname = None
if not sys.platform.startswith("win"):
	library = "libc.so.6"
	if sys.platform.startswith("darwin"):
		library = "/usr/lib/libc.dylib"
	elif sys.platform.startswith("sunos"):
		library = "libsocket.so.1"
	elif sys.platform.startswith("freebsd"):
		library = "/usr/lib/libc.so"
	elif sys.platform.startswith("openbsd"):
		library = "libc.so"
	try:
		from ctypes import cdll, CDLL, c_char_p, c_uint, create_string_buffer
		cdll.LoadLibrary(library)
		#<CDLL 'libc.so.6', handle 7fcac419b000 at 7fcac1ab0c10>
		_libc = CDLL(library)
		debug("successfully loaded socket C library from %s", library)
	except ImportError, e:
		log.error("library %s not found: %s", library, e)
	except OSError, e:
		log.error("error loading %s: %s", library, e)
	else:
		_libc.if_indextoname.restype = c_char_p
		def if_nametoindex(interfaceName):
			return _libc.if_nametoindex(interfaceName)
		def if_indextoname(index):
			s = create_string_buffer('\000' * 256)
			return _libc.if_indextoname(c_uint(index), s)
