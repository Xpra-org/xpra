/**
 * This file is part of Xpra.
 * Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
 */

//Just a wrapper for functions that are problematic to access with Cython

#import <Cocoa/Cocoa.h>

NSEventType getNSEventType(NSEvent *nsevent);
double getNSEventScrollingDeltaX(NSEvent *nsevent);
double getNSEventScrollingDeltaY(NSEvent *nsevent);
void *getNSEventView(NSEvent *nsevent);
