/**
 * This file is part of Xpra.
 * Copyright (C) 2018-2019 Antoine Martin <antoine@devloop.org.uk>
 */

//Just a wrapper for functions that are problematic to access with Cython

#import <Cocoa/Cocoa.h>

void setOpaque(NSWindow *window, BOOL opaque);
void setClearBackgroundColor(NSWindow *window);
