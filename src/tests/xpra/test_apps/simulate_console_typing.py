#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>

import sys
import time
import random

def print_text(text, words_per_minute=80):
	if not text:
		return
	n_chars = len(text)
	n_words = len(text.split())
	chars_per_word = float(n_chars)/n_words
	words_per_minute = 80
	chars_per_second = (chars_per_word*words_per_minute)/60.0
	#print("characters per word: %s" % chars_per_word)
	#print("words per minute: %s" % words_per_minute)
	#print("chars per second: %s" % chars_per_second)
	for char in text:
		sys.stdout.write(char)
		sys.stdout.flush()
		pause = 1.0/chars_per_second*(2.0*random.random())
		time.sleep(pause)

def main():
	text = "Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
	while True:
		print_text(text)

if __name__ == "__main__":
	main()
