#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

import avahi
import dbus
try:
	from dbus.exceptions import DBusException
except:
	#not available in all versions of the bindings?
	DBusException = Exception
XPRA_MDNS_TYPE = '_xpra._tcp.'

from xpra.log import Logger
log = Logger("network", "mdns")

from xpra.dbus.common import init_system_bus
from xpra.net.net_util import get_iface, if_nametoindex, if_indextoname

SHOW_INTERFACE = True			#publishes the name of the interface we broadcast from


def get_interface_index(host):
	log("get_interface_index(%s)", host)
	if host == "0.0.0.0" or host =="" or host=="*":
		return	avahi.IF_UNSPEC

	if not if_nametoindex:
		log.error("cannot convert interface to index (if_nametoindex is missing), so returning 'IF_UNSPEC', avahi will publish on ALL interfaces")
		return	avahi.IF_UNSPEC

	iface = get_iface(host)
	log("get_iface(%s)=%s", host, iface)
	if iface is None:
		return	avahi.IF_UNSPEC

	index = if_nametoindex(iface)
	log("if_nametoindex(%s)=%s", iface, index)
	if iface is None:
		return	avahi.IF_UNSPEC
	return index


class AvahiPublishers:
	"""
	Aggregates a number of AvahiPublisher(s).
	This takes care of constructing the appropriate AvahiPublisher
	with the interface index and port for the given list of (host,port)s to broadcast on,
	and to convert the text dict into a TXT string.
	"""

	def __init__(self, listen_on, service_name, service_type=XPRA_MDNS_TYPE, text_dict={}):
		self.publishers = []
		try:
			bus = init_system_bus()
		except Exception as e:
			log.warn("failed to connect to the system dbus: %s", e)
			log.warn(" either start a dbus session or disable mdns support")
			return
		for host, port in listen_on:
			iface_index = get_interface_index(host)
			log("iface_index(%s)=%s", host, iface_index)
			td = text_dict
			if SHOW_INTERFACE and if_indextoname and iface_index is not None:
				td = text_dict.copy()
				td["iface"] = if_indextoname(iface_index)
			txt = []
			if text_dict:
				for k,v in text_dict.items():
					txt.append("%s=%s" % (k,v))
			if host=="0.0.0.0":
				host = ""
			else:
				try:
					import socket
					host = socket.gethostbyaddr(host)[0]
				except:
					pass
			self.publishers.append(AvahiPublisher(bus, service_name, port, service_type, domain="", host=host, text=txt, interface=iface_index))

	def start(self):
		log("avahi:starting: %s", self.publishers)
		if not self.publishers:
			return
		all_err = True
		for publisher in self.publishers:
			if publisher.start():
				all_err = False
		if all_err:
			log.warn(" you may want to disable mdns support to avoid this warning")

	def stop(self):
		log("stopping: %s", self.publishers)
		for publisher in self.publishers:
			publisher.stop()


class AvahiPublisher:

	def __init__(self, bus, name, port, stype=XPRA_MDNS_TYPE, domain="", host="", text="", interface=avahi.IF_UNSPEC):
		log("AvahiPublisher%s", (bus, name, port, stype, domain, host, text, interface))
		self.bus = bus
		self.name = name
		self.stype = stype
		self.domain = domain
		self.host = host
		self.port = port
		self.text = text
		self.interface = interface
		self.group = None

	def __str__(self):
		return	"AvahiPublisher(%s %s:%s interface=%s)" % (self.name, self.host, self.port, self.interface)

	def start(self):
		try:
			server = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER), avahi.DBUS_INTERFACE_SERVER)
			g = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME, server.EntryGroupNew()), avahi.DBUS_INTERFACE_ENTRY_GROUP)
		except Exception as e:
			log.warn("failed to connect to avahi's dbus interface: %s", e)
			return False

		try:
			args = (self.interface, avahi.PROTO_UNSPEC,dbus.UInt32(0),
						 self.name, self.stype, self.domain, self.host,
						 dbus.UInt16(self.port), self.text)
			log("calling %s%s", g, args)
			g.AddService(*args)
			g.Commit()
			self.group = g
			log("dbus service added")
		except DBusException as e:
			#use try+except as older versions may not have those modules?
			message = e.get_dbus_message()
			dbus_error_name = e.get_dbus_name()
			if dbus_error_name=="org.freedesktop.Avahi.CollisionError":
				log.error("error starting publisher %s: another instance already claims this dbus name: %s, message: %s", self, e, message)
				return
			log.warn("failed to start %s: %s", self, e)
			return False
		return True

	def stop(self):
		log("%s.stop() group=%s", self, self.group)
		if self.group:
			try:
				self.group.Reset()
				self.group = None
			except Exception as e:
				log.error("error stopping publisher %s: %s", self, e)


def main():
	import glib
	import random, signal
	port = int(20000*random.random())+10000
	host = "0.0.0.0"
	name = "test service"
	publisher = AvahiPublisher(name, port, stype=XPRA_MDNS_TYPE, host=host, text="somename: somevalue")
	assert publisher
	glib.idle_add(publisher.start)
	signal.signal(signal.SIGTERM, exit)
	glib.MainLoop().run()


if __name__ == "__main__":
	main()
