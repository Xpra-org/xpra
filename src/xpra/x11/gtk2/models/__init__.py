# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


#if you want to use a virtual screen bigger than 32767x32767
#you will need to change those values, but some broken toolkits
#will then misbehave (they use signed shorts instead of signed ints..)
MAX_WINDOW_SIZE = 2**15-1
