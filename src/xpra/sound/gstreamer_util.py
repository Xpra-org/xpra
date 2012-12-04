#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from wimpiggy.log import Logger
log = Logger()

SOUND_TEST_MODE = os.environ.get("XPRA_SOUND_TEST", False)


VORBIS = "vorbis"
FLAC = "flac"
AAC = "aac"
MP3 = "mp3"

CODECS = {
#			VORBIS : (["vorbisenc"], ["vorbisdec"]),
#			FLAC : (["flacenc"], ["flacdec"]),
			AAC : (["faac"], ["faad"]),
			MP3 : (["lamemp3enc"], ["mad"]),
			}
CODEC_ORDER = [VORBIS, AAC, MP3, FLAC]

has_gst = False
all_plugin_names = []
try:
	import pygst
	pygst.require("0.10")
	import gst
	has_gst = True

	registry = gst.registry_get_default()
	all_plugin_names = [el.get_name() for el in registry.get_feature_list(gst.ElementFactory)]
	all_plugin_names.sort()
	log("found the following plugins: %s", all_plugin_names)
except ImportError, e:
	log.error("(py)gst seems to be missing: %s", e)

def has_plugins(*names):
	global all_plugin_names
	for name in names:
		if name not in all_plugin_names:
			#logger.sdebug("missing %s" % name, *names)
			return	False
	return	True

def get_encoders(name):
	if name not in CODECS:
		return []
	encoders, _ = CODECS.get(name)
	return [e for e in encoders if has_plugins(e)]

def get_decoders(name):
	if name not in CODECS:
		return []
	_, decoders = CODECS.get(name)
	return [e for e in decoders if has_plugins(e)]

def has_encoder(name):
	return len(get_encoders(name))>0

def has_decoder(name):
	return len(get_decoders(name))>0

def has_codec(name):
	return has_encoder(name) and has_decoder(name)

def can_encode():
	return [x for x in CODEC_ORDER if has_encoder(x)]

def can_decode():
	return [x for x in CODEC_ORDER if has_decoder(x)]


def plugin_str(plugin, options):
	s = "%s" % plugin
	if options:
		s += " "
		s += " ".join([("%s=%s" % (k,v)) for k,v in options.items()])
	return s

def add_gst_capabilities(capabilities, receive=True, send=True,
						receive_codecs=[], send_codecs=[]):
	capabilities["sound.decoders"] = receive_codecs
	capabilities["sound.encoders"] = send_codecs
	capabilities["sound.receive"] = receive and len(receive_codecs)>0
	capabilities["sound.send"] = send and len(send_codecs)>0


def start_sending_sound(remote_decoders, local_decoders, remote_pulseaudio_server, remote_pulseaudio_id):
	try:
		matching_codecs = [x for x in remote_decoders if x in local_decoders]
		if len(matching_codecs)==0:
			log.error("no matching codecs between remote (%s) and local (%s) - sound disabled", remote_decoders, local_decoders)
			return	None
		codec = matching_codecs[0]
		log.info("will send sound using %s codec", codec)
		from xpra.sound.src import SoundSource
		if SOUND_TEST_MODE:
			sound_source = SoundSource("audiotestsrc", {"wave":2, "freq":110, "volume":0.4}, codec, {})
			log.info("using test sound source")
		else:
			from xpra.sound.pulseaudio_util import has_pa, get_pa_device_options
			from xpra.sound.pulseaudio_util import get_pulse_server, get_pulse_id
			if not has_pa():
				log.error("pulseaudio not supported - sound disabled")
				return	None
			pa_server = get_pulse_server()
			log("start sound, remote pulseaudio server=%s, local pulseaudio server=%s", remote_pulseaudio_server, pa_server)
			if remote_pulseaudio_server and (remote_pulseaudio_server==pa_server or len(pa_server)>16 and remote_pulseaudio_server.endswith(pa_server)):
				log.error("identical pulseaudio server, refusing to create a sound loop - sound disabled")
				return	None
			pa_id = get_pulse_id()
			log("start sound, client id=%s, server id=%s", remote_pulseaudio_id, pa_id)
			if remote_pulseaudio_id and remote_pulseaudio_id==pa_id:
				log.error("identical pulseaudio ID, refusing to create a sound loop - sound disabled")
				return	None
			monitor_devices = get_pa_device_options(True, False)
			log("found pulseaudio monitor devices: %s", monitor_devices)
			if len(monitor_devices)==0:
				log.error("could not detect any pulseaudio monitor devices - sound forwarding is disabled")
				return	None
			monitor_device = monitor_devices.items()[0][0]
			sound_source = SoundSource("pulsesrc", {"device" : monitor_device}, codec, {})
			log.info("starting sound using %s", monitor_device)
		return sound_source
	except Exception, e:
		log.error("error setting up sound: %s", e, exc_info=True)
		return	None

def main():
	import logging
	logging.basicConfig(format="%(asctime)s %(message)s")
	logging.root.setLevel(logging.INFO)

	log.info("all gstreamer plugins: %s", all_plugin_names)


if __name__ == "__main__":
	main()
