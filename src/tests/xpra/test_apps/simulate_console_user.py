#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>

import sys
import subprocess

from tests.xpra.test_apps.simulate_console_typing import print_text

def simulate_commands(commands):
	prompt = "localhost> $ "
	for cmd in commands:
		sys.stdout.write(prompt)
		sys.stdout.flush()
		print_text(cmd)
		sys.stdout.write("\n")
		sys.stdout.flush()
		proc = subprocess.Popen(cmd, shell=True, stdout=sys.stdout, stderr=sys.stderr)
		proc.wait()
		#time.sleep(0.1+random.random())

def main():
	commands = ["ls -la", "clear", "echo hello there", "", "dmesg", "df", "ps -ef"]
	while True:
		simulate_commands(commands)

if __name__ == "__main__":
	main()
