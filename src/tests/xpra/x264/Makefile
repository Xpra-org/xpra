# This file is part of Parti.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# This makefile is only used for experimenting/testing
# The library and python bindings are built using the standard setup.py file

CFLAGS+=$(shell pkg-config  --cflags $(FFMPEG_LIBS))
LDFLAGS+=$(shell pkg-config --libs $(FFMPEG_LIBS)) -lm

CFLAGS+=-fPIC -W -g3 -O1

all: x264lib.so testlib

x264lib.so: x264lib.o
	$(CC) -shared -Wl,-soname,x264lib.so -o $@ $(LDFLAGS) $< -l x264 -lswscale -lavcodec
#static link: $(CC) -shared -Wl,-soname,x264lib.so -o $@ $(LDFLAGS) $< -Wl,-Bstatic -Wl,-Bsymbolic -lx264 -lswscale -lavcodec -Wl,-Bdynamic

x264lib.o: x264lib.c x264lib.h
	$(CC) $(CFLAGS) x264lib.c -c -o $@

testlib: x264lib.so testlib.c
	$(CC) $(CFLAGS) testlib.c -o $@ ./x264lib.so -l x264 -lswscale -lavcodec

OBJS=$(addsuffix .o,$(EXAMPLES))

.phony: all clean


clean:
	rm -rf x264lib.so x264lib.o
