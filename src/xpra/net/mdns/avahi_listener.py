#!/usr/bin/env python

# This file is part of Xpra.
# Copyright (C) 2009-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import avahi
import dbus

from xpra.net.mdns import XPRA_MDNS_TYPE
from xpra.dbus.common import init_system_bus
from xpra.dbus.helper import dbus_to_native

from xpra.log import Logger
log = Logger("network", "mdns")


class AvahiListener:

	def __init__(self, service_type, mdns_found=None, mdns_add=None, mdns_remove=None):
		log("AvahiListener%s", (service_type, mdns_found, mdns_add, mdns_remove))
		try:
			self.bus = init_system_bus()
			assert self.bus
		except Exception as e:
			log.warn("failed to connect to the system dbus: %s", e)
			log.warn(" either start a dbus session or disable mdns support")
			return
		self.sdref = None
		self.readers = []
		self.resolvers = []
		self.service_type = service_type
		self.mdns_found = mdns_found
		self.mdns_add = mdns_add
		self.mdns_remove = mdns_remove
		self.server = None

	def resolve_error(self, *args):
		log.error("AvahiListener.resolve_error%s", args)

	def service_resolved(self, interface, protocol, name, stype, domain, host, x, address, port, text_array, v):
		log("AvahiListener.service_resolved%s", (interface, protocol, name, stype, domain, host, x, address, port, "..", v))
		if self.mdns_add:
			#parse text data:
			text = {}
			try:
				for text_line in text_array:
					line = ""
					for b in text_line:
						line += chr(b.real)
					parts = line.split("=", 1)
					if len(parts)==2:
						text[parts[0]] = parts[1]
				log(" text=%s", text)
			except Exception:
				log.error("failed to parse text record", exc_info=True)
			nargs = (dbus_to_native(x) for x in (interface, protocol, name, stype, domain, host, address, port, text))
			self.mdns_add(*nargs)

	def service_found(self, interface, protocol, name, stype, domain, flags):
		log("service_found%s", (interface, protocol, name, stype, domain, flags))
		if flags & avahi.LOOKUP_RESULT_LOCAL:
			# local service, skip
			pass
		if self.mdns_found:
			self.mdns_found(dbus_to_native(interface), dbus_to_native(name))
		self.server.ResolveService(interface, protocol, name, stype,
				domain, avahi.PROTO_UNSPEC, dbus.UInt32(0),
				reply_handler=self.service_resolved, error_handler=self.resolve_error)

	def service_removed(self, interface, protocol, name, stype, domain, flags):
		log("service_removed%s", (interface, protocol, name, stype, domain, flags))
		if self.mdns_remove:
			nargs = (dbus_to_native(x) for x in (interface, protocol, name, stype, domain, flags))
			self.mdns_remove(*nargs)


	def start(self):
		self.server = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME, '/'), 'org.freedesktop.Avahi.Server')
		log("AvahiListener.start() server=%s", self.server)

		self.sbrowser = dbus.Interface(self.bus.get_object(avahi.DBUS_NAME,
								self.server.ServiceBrowserNew(avahi.IF_UNSPEC,
								avahi.PROTO_UNSPEC, XPRA_MDNS_TYPE, 'local', dbus.UInt32(0))),
								avahi.DBUS_INTERFACE_SERVICE_BROWSER)
		log("AvahiListener.start() service browser=%s", self.sbrowser)
		self.sbrowser.connect_to_signal("ItemNew", self.service_found)
		self.sbrowser.connect_to_signal("ItemRemove", self.service_removed)

	def stop(self):
		#FIXME: how do we tell dbus we are no longer interested?
		pass


def main():
	def mdns_found(*args):
		print("mdns_found: %s" % (args, ))
	def mdns_add(*args):
		print("mdns_add: %s" % (args, ))
	def mdns_remove(*args):
		print("mdns_remove: %s" % (args, ))

	from xpra.dbus.common import loop_init
	loop_init()
	listener = AvahiListener(XPRA_MDNS_TYPE, mdns_found, mdns_add, mdns_remove)
	try:
		from xpra.gtk_common.gobject_compat import import_glib
		glib = import_glib()
		glib.idle_add(listener.start)
		glib.MainLoop().run()
	finally:
		listener.stop()


if __name__ == "__main__":
	main()
