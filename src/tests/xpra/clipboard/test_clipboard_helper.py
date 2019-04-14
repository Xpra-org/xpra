#!/usr/bin/env python

from xpra.platform import program_context
from xpra.platform.win32.clipboard import Win32Clipboard, log

def main():
	with program_context("Clipboard-Test", "Clipboard Test Tool"):
		def send_packet_cb(*args):
			print("send_packet_cb%s" % (args,))
		def progress_cb(*args):
			print("progress_cb%s" % (args,))
		try:
			log("creating %s", Win32Clipboard)
			c = Win32Clipboard(send_packet_cb, progress_cb)
			log("sending all tokens")
			c.enable_selections(["CLIPBOARD"])
			c.set_direction(True, True)
			c.send_all_tokens()
			log("faking clipboard request")
			c._process_clipboard_request(["clipboard-request", 1, "CLIPBOARD", "TARGETS"])
			def set_contents():
				pass
			#c._process_clipboard_token(["clipboard-token", "CLIPBOARD", ])
			#_process_clipboard_contents(self, packet):
			from xpra.gtk_common.gobject_compat import import_glib
			glib = import_glib()
			main_loop = glib.MainLoop()
			glib.timeout_add(1000, set_contents)
			log("main loop=%s", main_loop)
			main_loop.run()
		except:
			log.error("", exc_info=True)

if __name__ == "__main__":
	main()
