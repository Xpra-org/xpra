/**
 * This file is part of Xpra.
 * Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
 */

#import <Cocoa/Cocoa.h>

NSEventType getNSEventType(NSEvent *nsevent) {
	return [nsevent type];
}

double getNSEventScrollingDeltaX(NSEvent *nsevent) {
	return [nsevent scrollingDeltaX];
}
double getNSEventScrollingDeltaY(NSEvent *nsevent) {
	return [nsevent scrollingDeltaY];
}
void *getNSEventView(NSEvent *nsevent) {
	return [[nsevent window] contentView];
}

int getPreciseScrollingDeltas(NSEvent *nsevent) {
	return [nsevent hasPreciseScrollingDeltas];
}