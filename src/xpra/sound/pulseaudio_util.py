#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2010-2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import subprocess

from wimpiggy.log import Logger
log = Logger()


def which(name):
	if sys.platform.startswith("win"):
		return	""
	cmd = ["which", name]
	try:
		proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out, _ = proc.communicate()
		if proc.returncode!=0 or not out:
			return ""
		c = out.replace("\n", "").replace("\r", "")
		if os.path.exists(c):
			return	c
	except:
		return	""

pactl_bin = which("pactl")
has_pulseaudio = None

def pactl_output(pactl_cmd):
	#ie: "pactl list"
	cmd = [pactl_bin, pactl_cmd]
	try:
		proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out, _ = proc.communicate()
		code = proc.wait()
		return  code, out
	except Exception, e:
		log.error("failed to execute %s: %s", cmd, e)
		return  -1, None

def detect_pa():
	if not pactl_bin:
		return False
	if not os.path.exists(pactl_bin) or not os.path.isfile(pactl_bin):
		return False
	if os.name=="posix" and not os.access(pactl_bin, os.X_OK):
		return False
	status, _ = pactl_output("stat")
	return status==0

def has_pa():
	global has_pulseaudio
	if has_pulseaudio is None:
		has_pulseaudio = detect_pa()
	return has_pulseaudio


def get_x11_property(atom_name):
	from gtk import gdk
	root = gdk.get_default_root_window()
	try:
		pulse_server_atom = gdk.atom_intern(atom_name)
		p = root.property_get(pulse_server_atom)
		if p is None:
			return ""
		v = p[2]
		log("%s=%s", atom_name, v)
		return v
	except:
		return ""

def get_pactl_server():
	code, out = pactl_output("info")
	if code!=0:
		return	""
	for line in out.splitlines():
		if line.startswith("Server String: "):
			return line[len("Server String: "):]
	return ""

def get_pulse_server():
	return get_x11_property("PULSE_SERVER") or get_pactl_server()

def get_pulse_id():
	return get_x11_property("PULSE_ID")


def add_audio_tagging_env(icon_path=None):
	"""
		This is called audio-tagging in PulseAudio, see:
		http://pulseaudio.org/wiki/ApplicationProperties
		http://0pointer.de/blog/projects/tagging-audio.html
	"""
	os.environ["PULSE_PROP_application.name"] = "xpra"
	os.environ["PULSE_PROP_media.role"] = "music"
	if icon_path and os.path.exists(icon_path):
		os.environ["PULSE_PROP_application.icon_name"] = icon_path


def get_pa_device_options(monitors=False, input_or_output=None, ignored_devices=["bell-window-system"]):
	"""
	Finds the list of devices, monitors=False allows us to filter out monitors
	(which could create sound loops if we use them)
	set input_or_output=True to get inputs only
	set input_or_output=False to get outputs only
	set input_or_output=None to get both
	Same goes for monitors (False|True|None)
	Returns the a dict() with the PulseAudio name as key and a description as value
	"""
	if sys.platform.startswith("win") or sys.platform.startswith("darwin"):
		return {}
	status, out = pactl_output("list")
	if status!=0 or not out:
		return  {}
	device_class = None
	device_description = None
	name = None
	devices = {}
	for line in out.splitlines():
		if not line.startswith(" ") and not line.startswith("\t"):		#clear vars when we encounter a new section
			if name and device_class:
				if name in ignored_devices:
					continue
				#Verify against monitor flag if set:
				if monitors is not None:
					is_monitor = device_class=='"monitor"'
					if is_monitor!=monitors:
						continue
				#Verify against input flag (if set):
				if input_or_output is not None:
					is_input = name.find("input")>=0
					if is_input is True and input_or_output is False:
						continue
					is_output = name.find("output")>=0
					if is_output is True and input_or_output is True:
						continue
				if not device_description:
					device_description = name
				devices[name] = device_description
			name = None; device_class = None
		line = line.strip()
		if line.startswith("Name: "):
			name = line[len("Name: "):]
		if line.startswith("device.class = "):
			device_class = line[len("device-class = "):]
		if line.startswith("device.description = "):
			device_description = line[len("device.description = "):].strip('"')
	return devices

def add_pulseaudio_capabilities(capabilities):
	capabilities["sound.pulseaudio.id"] = get_pulse_id()
	capabilities["sound.pulseaudio.server"] = get_pulse_server()


def main():
	import logging
	logging.basicConfig(format="%(asctime)s %(message)s")
	logging.root.setLevel(logging.INFO)

	for monitors in (True, False):
		for io in (True, False):
			devices = get_pa_device_options(monitors, io)
			log.info("devices(%s,%s)=%s", monitors, io, devices)


if __name__ == "__main__":
	main()
