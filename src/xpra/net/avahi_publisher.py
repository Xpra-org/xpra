#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# taken from the code I wrote for winswitch

import avahi
import dbus

XPRA_MDNS_TYPE = '_xpra._tcp.'

from xpra.log import Logger, debug_if_env
log = Logger()
debug = debug_if_env(log, "XPRA_MDNS_DEBUG")

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
	if not iface:
		return	None

	return	if_nametoindex(iface)


class AvahiPublishers:
	"""
	Aggregates a number of AvahiPublisher(s).
	This takes care of constructing the appropriate AvahiPublisher
	with the interface index and port for the given list of (host,port)s to broadcast on,
	and to convert the text dict into a TXT string.
	"""

	def __init__(self, listen_on, service_name, service_type=XPRA_MDNS_TYPE, text_dict={}):
		self.publishers = []
		for host, port in listen_on:
			iface_index = get_interface_index(host)
			debug("iface_index(%s)=%s", host, iface_index)
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
			self.publishers.append(AvahiPublisher(service_name, port, service_type, domain="", host=host, text=txt, interface=iface_index))
	
	def start(self):
		for publisher in self.publishers:
			try:
				publisher.start()
			except Exception, e:
				log.error("error on publisher %s", publisher, exc_info=True)
				try:
					import dbus.exceptions
					if type(e)==dbus.exceptions.DBusException:
						message = e.get_dbus_message()
						dbus_error_name = e.get_dbus_name()
						if dbus_error_name=="org.freedesktop.Avahi.CollisionError":
							log.error("error starting publisher %s: another instance already claims this dbus name: %s, message: %s", publisher, e, message)
							continue
				except:
					pass
				log.error("error on publisher %s: %s", publisher, e)

	def stop(self):
		debug("stopping: %s", self.publishers)
		for publisher in self.publishers:
			try:
				publisher.stop()
			except Exception, e:
				log.error("error stopping publisher %s: %s", publisher, e)


class AvahiPublisher:

	def __init__(self, name, port, stype=XPRA_MDNS_TYPE, domain="", host="", text="", interface=avahi.IF_UNSPEC):
		debug("AvahiPublisher%s", (name, port, stype, domain, host, text, interface))
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
		bus = dbus.SystemBus()
		server = dbus.Interface(bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER), avahi.DBUS_INTERFACE_SERVER)

		g = dbus.Interface(bus.get_object(avahi.DBUS_NAME, server.EntryGroupNew()), avahi.DBUS_INTERFACE_ENTRY_GROUP)

		try:
			g.AddService(self.interface, avahi.PROTO_UNSPEC,dbus.UInt32(0),
						 self.name, self.stype, self.domain, self.host,
						 dbus.UInt16(self.port), self.text)
			g.Commit()
			self.group = g
		except Exception, e:
			log.warn("failed to start %s: %s", self, e)

	def stop(self):
		if self.group:
			self.group.Reset()


def main():
	import gobject
	gobject.threads_init()
	import random, signal
	port = int(20000*random.random())+10000
	host = "0.0.0.0"
	name = "test service"
	publisher = AvahiPublisher(name, port, stype=XPRA_MDNS_TYPE, host=host, text="somename: somevalue")
	assert publisher
	gobject.idle_add(publisher.start)
	signal.signal(signal.SIGTERM, exit)
	gobject.MainLoop().run()


if __name__ == "__main__":
	main()
