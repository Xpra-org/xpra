/*****************************************************************
Copyright (c) 1991, 1997 Digital Equipment Corporation, Maynard, Massachusetts.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software.

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
DIGITAL EQUIPMENT CORPORATION BE LIABLE FOR ANY CLAIM, DAMAGES, INCLUDING,
BUT NOT LIMITED TO CONSEQUENTIAL OR INCIDENTAL DAMAGES, OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Except as contained in this notice, the name of Digital Equipment Corporation
shall not be used in advertising or otherwise to promote the sale, use or other
dealings in this Software without prior written authorization from Digital
Equipment Corporation.
******************************************************************/

#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>

//FIXME: we should use the Display specified in the method call
//rather than relying on the DISPLAY environment variable.

//#define DEBUG

static time_t mtime = 0;
static int num_screens = 0;
static struct
{
	int width_mm, height_mm;
} screen_info[10];

static void skipComments(FILE* f)
{
	char tmp[4096];
	for(;;)
	{
		int c;
		for(;;)
		{
			c = fgetc(f);
			if (c == EOF)
				return;
			if (c != ' ' && c != '\t' && c != '\n')
				break;
		}
		if (c != '#')
		{
			ungetc( c, f );
			return;
		}
		fgets( tmp, 4096, f );
	}
}

static void initFakeDPI()
{
	struct stat sb;
	const char* home;
	const char* display;
	char buf[4096];
	FILE* f = NULL;
	int i;

#ifdef DEBUG
	fprintf(stderr, "libfakeXdpi.initFakeDPI()\n");
#endif

	home = getenv("HOME");

	if (home == NULL)
		return;

	display = getenv("DISPLAY");
#ifdef DEBUG
	fprintf(stderr, "libfakeXdpi.initFakeDPI() DISPLAY=%s, HOME=%s\n", display, home);
#endif
	if (display != NULL) {
		sprintf(buf, "%s/.%s-fakexscreenmm", home, display);
		if (stat(buf, &sb) == 0) {
			//the file was found
			if (sb.st_mtime<=mtime) {
				//unchanged or older than what we have loaded already
#ifdef DEBUG
			fprintf(stderr, "libfakeXdpi.initFakeDPI() keeping existing values for %s\n", buf);
#endif
				return;
			}
			f = fopen(buf, "r");
#ifdef DEBUG
			fprintf(stderr, "libfakeXdpi.initFakeDPI() new(er) file found: %s\n", buf);
#endif
		}
	}
	if (f == NULL)
		return;
	//keep track of the mtime of the file we load from:
	mtime = sb.st_mtime;

	//start parsing:
	skipComments(f);
	if (fscanf(f, "%d\n", &num_screens) != 1)
	{
#ifdef DEBUG
		fprintf(stderr, "libfakeXdpi.initFakeDPI() failed to parse number of screens");
#endif
		num_screens = 0;
		fclose(f);
		return;
	}
	if (num_screens >= 10)
		num_screens = 10;
	for (i = 0; i < num_screens; ++i)
	{
		skipComments(f);
		if (fscanf(f, "%d %d\n", &screen_info[i].width_mm, &screen_info[i].height_mm) != 2)
		{
#ifdef DEBUG
			fprintf(stderr, "libfakeXdpi.initFakeDPI() failed to parse dimensions for screen %i\n", i);
#endif
			num_screens = 0;
			fclose(f);
			return;
		}
	}
#ifdef DEBUG
	fprintf(stderr, "libfakeXdpi.initFakeDPI() found %i screens\n", num_screens);
#endif
	fclose(f);
}


int XDisplayWidthMM(Display *display, int screen_number)
{
	initFakeDPI();
	int w = 500;
	if (num_screens>0 && screen_number>=0 && screen_number<num_screens) {
		w = screen_info[screen_number].width_mm;
	}
#ifdef DEBUG
	fprintf(stderr, "libfakeXdpi.XDisplayWidthMM(%i)=%i (%i screens)\n", screen_number, w, num_screens);
#endif
	return w;
}

int XDisplayHeightMM(Display *display, int screen_number)
{
	initFakeDPI();
	int h = 300;
	if (num_screens>0 && screen_number>=0 && screen_number<num_screens) {
		h = screen_info[screen_number].height_mm;
	}
#ifdef DEBUG
	fprintf(stderr, "libfakeXdpi.XDisplayHeightMM(%i)=%i (%i screens)\n", screen_number, h, num_screens);
#endif
	return h;
}
