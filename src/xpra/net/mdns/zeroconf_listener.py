#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket
from xpra.log import Logger
log = Logger("network", "mdns")

from zeroconf import ServiceBrowser, Zeroconf		#@UnresolvedImport

class ZeroconfListener(object):

	def __init__(self, service_type, mdns_found=None, mdns_add=None, mdns_remove=None):
		log("ZeroconfListener%s", (service_type, mdns_found, mdns_add, mdns_remove))
		self.zeroconf = Zeroconf()
		self.browser = None
		if not service_type.endswith("local."):
			service_type += "local."
		self.service_type = service_type
		self.mdns_found = mdns_found
		self.mdns_add = mdns_add
		self.mdns_remove = mdns_remove

	def __repr__(self):
		return "ZeroconfListener(%s)" % self.service_type

	def remove_service(self, zeroconf, stype, name):
		log.info("remove_service%s", (zeroconf, stype, name))
		if self.mdns_remove:
			domain = "local"
			self.mdns_remove(0, 0, name, stype, domain, 0)

	def add_service(self, zeroconf, stype, name):
		log.info("add_service%s", (zeroconf, stype, name))
		info = zeroconf.get_service_info(stype, name)
		log.info("service info: %s", info)
		if self.mdns_add:
			interface = 0
			protocol = 0
			name = info.name
			domain = "local"
			address = socket.inet_ntoa(info.address)
			self.mdns_add(interface, protocol, info.name, info.type, domain, info.server, address, info.port, info.properties)

	def start(self):
		self.browser = ServiceBrowser(self.zeroconf, self.service_type, listener=self)
		log.info("ServiceBrowser%s=%s", (self.zeroconf, self.service_type, self), self.browser)

	def stop(self):
		b = self.browser
		if b:
			self.browser = None
			try:
				b.cancel()
			except:
				pass
		zc = self.zeroconf
		if zc:
			self.zeroconf = None
			try:
				zc.close()
			except:
				pass


def main():
	def mdns_found(*args):
		print("mdns_found: %s" % (args, ))
	def mdns_add(*args):
		print("mdns_add: %s" % (args, ))
	def mdns_remove(*args):
		print("mdns_remove: %s" % (args, ))

	from xpra.gtk_common.gobject_compat import import_glib
	glib = import_glib()
	glib.threads_init()
	loop = glib.MainLoop()

	from xpra.platform import program_context
	with program_context("zeroconf-listener", "zeroconf-listener"):
		from xpra.net.mdns import XPRA_MDNS_TYPE
		listener = ZeroconfListener(XPRA_MDNS_TYPE+"local.", mdns_found, mdns_add, mdns_remove)
		log("listener=%s" % listener)
		listener.start()
		try:
			loop.run()
		finally:
			listener.stop()


if __name__ == "__main__":
	main()
