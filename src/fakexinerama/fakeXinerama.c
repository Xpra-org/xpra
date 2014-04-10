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

#include <X11/Xlibint.h>
#include <X11/extensions/Xinerama.h>
#include <stdio.h>
#include <sys/stat.h>

//FIXME: we should use the Display specified in the method call
//rather than relying on the DISPLAY environment variable.

//#define DEBUG

static time_t mtime = 0;
static int num_screens = 0;
static struct
{
	int x_org, y_org;
	int width, height;
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

static void initFakeXinerama()
{
	struct stat sb;
	const char* home;
	const char* display;
	char buf[4096];
	FILE* f = NULL;
	int i;

#ifdef DEBUG
	fprintf(stderr, "libfakeXinerama.initFakeXinerama()\n");
#endif

	home = getenv("HOME");

	if (home == NULL)
		return;

	display = getenv("DISPLAY");
#ifdef DEBUG
	fprintf(stderr, "libfakeXinerama.initFakeXinerama() DISPLAY=%s, HOME=%s\n", display, home);
#endif
	if (display != NULL) {
		sprintf(buf, "%s/.%s-fakexinerama", home, display);
		if (stat(buf, &sb) == 0) {
			//the file was found
			if (sb.st_mtime<=mtime) {
				//unchanged or older than what we have loaded already
				//don't test for the generic file below, this one takes precedence
				return;
			}
			f = fopen(buf, "r");
#ifdef DEBUG
			fprintf(stderr, "fakexinerama: new(er) file found: %s\n", buf);
#endif
		}
	}
	if (f == NULL) {
		sprintf(buf, "%s/.fakexinerama", home);
		if (stat(buf, &sb) == 0) {
			//the file was found
			if (sb.st_mtime<=mtime)
				//unchanged or older than what we have loaded already
				return;
			f = fopen(buf, "r");
#ifdef DEBUG
			fprintf(stderr, "fakexinerama: new(er) file found: %s\n", buf);
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
		num_screens = 0;
		fclose(f);
		return;
	}
	if (num_screens >= 10)
		num_screens = 10;
	for (i = 0; i < num_screens; ++i)
	{
		skipComments(f);
		if (fscanf(f, "%d %d %d %d\n", &screen_info[i].x_org, &screen_info[i].y_org,
			&screen_info[i].width, &screen_info[i].height) != 4)
		{
			num_screens = 0;
			fclose(f);
			return;
		}
	}
#ifdef DEBUG
	fprintf(stderr, "libfakeXinerama.initFakeXinerama() found %i screens\n", num_screens);
#endif
	fclose(f);
}

Bool XineramaQueryExtension(Display *dpy, int *event_base, int *error_base)
{
	(void) dpy;
	*event_base = 0;
	*error_base = 0;
	return True;
}

Status XineramaQueryVersion(Display *dpy, int *major, int *minor)
{
	(void) dpy;
	*major = 1;
	*minor = 1;
	return 1;
}

Bool XineramaIsActive(Display *dpy)
{
	(void) dpy;
	initFakeXinerama();
	return num_screens>0;
}

XineramaScreenInfo *XineramaQueryScreens(Display *dpy, int *number)
{
	XineramaScreenInfo	*scrnInfo = NULL;
	initFakeXinerama();

	if (num_screens>0) {
		if ((scrnInfo = Xmalloc(sizeof(XineramaScreenInfo) * num_screens))) {
			int i;
			for(i = 0; i < num_screens; i++) {
				scrnInfo[i].screen_number = i;
				scrnInfo[i].x_org 	  = screen_info[i].x_org;
				scrnInfo[i].y_org 	  = screen_info[i].y_org;
				scrnInfo[i].width 	  = screen_info[i].width;
				scrnInfo[i].height 	  = screen_info[i].height;
			}
			*number = num_screens;
		}
	}
	return scrnInfo;
}
