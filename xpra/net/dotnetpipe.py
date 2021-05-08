# This file is part of Xpra.
# Copyright (C) 2021 Tribion B.V, Tijs van der Zwaan <tijzwa@vpo.nl>
# Copyright (C) 2011-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008, 2009, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import socket, os, struct, json, base64
from xpra.util import envbool
from xpra.log import Logger

log = Logger("network", "protocol")

class dotnetpipeclient:
	def __init__(self):
		self.enabled = envbool("XPRA_DOTNET_MIRROR", False)
		self.path = os.environ.get("XPRA_DOTNET_MIRROR_SOCKET", "/tmp/CoreFxPipe_xpraDotnetPipe")
		self.connected = False
		self.sock = None
		self.mirror_packages = ('hello', 'new-window', 'lost-window', 'window-metadata', 'window-icon', 'desktop_size')

	def connect_pipe(self):
		self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		try:
			self.sock.connect(self.path)
			self.connected = True
		except socket.error:
			log("sock.connect(%s) failed. Will retry on next packet.", self.path)

	def end (self):
		log("ending pipeconnection")
		try:
			if self.connected:
				self.sock.close()
		except:
			pass


	def mirror_package (self, type, packet):
		try:
			if not self.connected:
				log("No pipe connected. Will retry on next packet.")
				self.connect_pipe()
			if self.connected:
				msg = ""
				if type == 'helo':
					msg = {
						"type": "new-xpra-connection"
					}
				elif type == 'new-window':
					decorations = "1"
					windowtype = "NORMAL"
					title = ""
					try:
						decorations = str(packet[6]['decorations'])
					except:
						pass
					try:
						windowtype = str(packet[6]['window-type'])
					except:
						pass
					try:
						title = str(packet[6]['title'])
					except:
						pass			
					msg = {
						"type": type,
						"win": str(packet[1]),
						"decorations": decorations,
						"windowstype": windowtype,
						"title": title	
					}
				elif type == 'lost-window':
					msg = {
						"type": type,
						"win": str(packet[1])		
					}			
				elif type == 'window-metadata':
					title = ""
					try:
						title = str(packet[2]['title'])
					except:
						pass					
					msg = {
						"type": type,
						"win": str(packet[1]),
						"title"	: title
					}
				elif type =='window-icon':
					icodata = ""
					try:
						icodata = str(base64.b64encode(packet[5].data))
					except:
						pass
					msg = {
						"type": type,
						"win": str(packet[1]),
						"encoding" : str(packet[4]),
						"data" :  icodata
					}
				elif type =='desktop_size':
					msg = {
						"type": type,
						"w": str(packet[1]),
						"h" : str(packet[2])
					}
				bMsg = json.dumps(msg).encode('utf-8')
				self.sock.sendall(bMsg)
		except socket.error as err:
			log("Socket error in dotnetpipe. Will retry on next packet.")
			try:
				self.sock.close()
			except:
				pass
			self.connected = False
