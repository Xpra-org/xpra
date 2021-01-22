#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>

import sys
import random
import subprocess
from time import sleep

from xpra.test_apps.simulate_console_typing import print_text

def simulate_commands(commands):
	prompt = "localhost> $ "
	for cmd in commands:
		sys.stdout.write(prompt)
		sys.stdout.flush()
		if cmd:
			print_text(cmd)
		else:
			sleep(0.01+random.random()/4)
		sys.stdout.write("\n")
		sys.stdout.flush()
		if cmd:
			proc = subprocess.Popen(cmd, shell=True, stdout=sys.stdout, stderr=sys.stderr)
			proc.wait()

def main():
	commands = [
		"ls -la",
		"clear",
		"echo hello there",
		"",
		"dmesg",
		"df",
		] + \
		[""]*20+ \
		[
			"ps -ef",
		] + \
		[""]*5 + \
		["echo gap1"] + \
		[""]*5 + \
		["echo gap2"] + \
		[""]*70
	while True:
		simulate_commands(commands)

if __name__ == "__main__":
	main()
