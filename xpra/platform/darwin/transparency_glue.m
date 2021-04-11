/**
 * This file is part of Xpra.
 * Copyright (C) 2018-2019 Antoine Martin <antoine@devloop.org.uk>
 */

#import <Cocoa/Cocoa.h>

void setOpaque(NSWindow *window, BOOL opaque) {
	[window setOpaque:opaque];
}
void setClearBackgroundColor(NSWindow *window) {
	NSColor *color = [NSColor clearColor];
	[window setBackgroundColor:color];
}
void setBackgroundColor(NSWindow *window, NSColor *color) {
	[window setBackgroundColor:color];
}
