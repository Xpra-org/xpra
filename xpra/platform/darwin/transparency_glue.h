/**
 * This file is part of Xpra.
 * Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
 */

//Just a wrapper for functions that are problematic to access with Cython

#import <Cocoa/Cocoa.h>

void setOpaque(NSWindow *window, BOOL opaque);
void setClearBackgroundColor(NSWindow *window);

float getBackingScaleFactor(NSWindow *window);
