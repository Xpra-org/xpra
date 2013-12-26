/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Licensed under MPL 2.0
 *
 * xpra window
 *
 * Based on shape.js
 */


function XpraWindow(canvas_state, x, y, w, h, metadata, override_redirect, client_properties,
		geometry_cb, mouse_move_cb, mouse_click_cb) {
	"use strict";
	// This is a very simple and unsafe constructor. All we're doing is checking if the values exist.
	// "x || 0" just means "if there is a value for x, use that. Otherwise use 0."
	// But we aren't checking anything else! We could put "Lalala" for the value of x
	//keep reference to the canvas:
	this.state = canvas_state;

	//xpra specific attributes:
	this.metadata = metadata;
	this.override_redirect = override_redirect;
	this.client_properties = client_properties;
	this.geometry_cb = geometry_cb || null;
	this.mouse_move_cb = mouse_move_cb || null;
	this.mouse_click_cb = mouse_click_cb || null;

	// the space taken by window decorations:
	this.borderColor = '#101028';
	if (override_redirect) {
		this.borderWidth = 0;
		this.topBarHeight = 0;
	}
	else {
		this.borderWidth = 2;
		this.topBarHeight = 20;
	}
	this.topBarColor = '#A8A8B0';
	this.offsets = [this.borderWidth+this.topBarHeight, this.borderWidth, this.borderWidth, this.borderWidth];

	// account for borders, and try to make the image area map to (x,y):
	var rx = (x || 0) - this.borderWidth;
	var ry = (y || 0) - this.topBarHeight + this.borderWidth;
	var rw = (w || 1) + this.borderWidth*2;
	var rh = (h || 1) + this.borderWidth*2 + this.topBarHeight;
	// so we can call move_resize safely without firing a callback that does not exist:
	this.geometry_cb = null;
	this.move_resize(rx, ry, rw, rh);

	//create the image holding the pixels (the "backing"):
	this.image = canvas_state.canvas.getContext('2d').createImageData(w, h);
	canvas_state.addShape(this);
};

XpraWindow.prototype.move_resize = Shape.prototype.move_resize;
XpraWindow.prototype.move = Shape.prototype.move;
XpraWindow.prototype.resize = Shape.prototype.resize;
XpraWindow.prototype.get_window_geometry = Shape.prototype.get_window_geometry;

// The geometry of the window image:
XpraWindow.prototype.get_internal_geometry = function(ctx) {
	"use strict";
	// This should always be true:
	//this.image.width = this.w - this.borderWidth*2;
	//this.image.height = this.h - (this.borderWidth*2 + this.topBarHeight);
	return { x : this.x+this.borderWidth,
			 y : this.y+this.borderWidth+this.topBarHeight,
			 w : this.image.width,
			 h : this.image.height };
};

XpraWindow.prototype.handle_mouse_click = function(button, pressed, mx, my, modifiers, buttons) {
	var igeom = this.get_internal_geometry();
	if (this.mouse_click_cb!=null && rectangle_contains(igeom, mx, my)) {
		this.mouse_click_cb(this, button, pressed, mx, my, modifiers, buttons);
	}
};

XpraWindow.prototype.handle_mouse_move = function(mx, my, modifiers, buttons) {
	var igeom = this.get_internal_geometry();
	if (this.mouse_move_cb!=null && rectangle_contains(igeom, mx, my)) {
		this.mouse_move_cb(this, mx, my, modifiers, buttons);
	}
};

// Draws this shape to a given context
XpraWindow.prototype.draw = function(ctx) {
	"use strict";

	if (!this.override_redirect)
		//draw window frame:
		this.draw_frame(ctx);

	//draw the window pixels:
	ctx.putImageData(this.image, this.x + this.borderWidth, this.y + this.borderWidth + this.topBarHeight);

	if (this.state.selection === this && !this.override_redirect) {
		//window.alert("Shape.prototype.draw_selection="+Shape.prototype.draw_selection);
		this.draw_selection(ctx);
	}
};

// Draws window frame
XpraWindow.prototype.draw_frame = function(ctx) {
	"use strict";

	// draw border:
	ctx.strokeStyle = this.borderColor;
	ctx.lineWidth = this.borderWidth;
	var hw = this.borderWidth/2;
	ctx.strokeRect(this.x+hw,this.y+hw,this.w-this.borderWidth,this.h-this.borderWidth);

	// draw top bar:
	ctx.fillStyle = this.topBarColor;
	ctx.fillRect(this.x+this.borderWidth, this.y+this.borderWidth, this.w-this.borderWidth*2, this.topBarHeight-this.borderWidth);
};


// Draws border and selection rectangles
// which indicate that the window is selected
XpraWindow.prototype.draw_selection = function(ctx) {
	"use strict";
	var i, cur, half;

	ctx.strokeStyle = this.state.selectionColor;
	ctx.lineWidth = this.state.selectionWidth;
	ctx.strokeRect(this.x,this.y,this.w,this.h);

	// draw the boxes
	half = this.state.selectionBoxSize / 2;

	// 0  1  2
	// 3     4
	// 5  6  7

	// top left, middle, right
	this.state.selectionHandles[0].x = this.x-half;
	this.state.selectionHandles[0].y = this.y-half;

	this.state.selectionHandles[1].x = this.x+this.w/2-half;
	this.state.selectionHandles[1].y = this.y-half;

	this.state.selectionHandles[2].x = this.x+this.w-half;
	this.state.selectionHandles[2].y = this.y-half;

	//middle left
	this.state.selectionHandles[3].x = this.x-half;
	this.state.selectionHandles[3].y = this.y+this.h/2-half;

	//middle right
	this.state.selectionHandles[4].x = this.x+this.w-half;
	this.state.selectionHandles[4].y = this.y+this.h/2-half;

	//bottom left, middle, right
	this.state.selectionHandles[6].x = this.x+this.w/2-half;
	this.state.selectionHandles[6].y = this.y+this.h-half;

	this.state.selectionHandles[5].x = this.x-half;
	this.state.selectionHandles[5].y = this.y+this.h-half;

	this.state.selectionHandles[7].x = this.x+this.w-half;
	this.state.selectionHandles[7].y = this.y+this.h-half;

	ctx.fillStyle = this.state.selectionBoxColor;
	for (i = 0; i < 8; i += 1) {
		cur = this.state.selectionHandles[i];
		ctx.fillRect(cur.x, cur.y, this.state.selectionBoxSize, this.state.selectionBoxSize);
	}
};

// Updates the window image with new pixel data
XpraWindow.prototype.paint = function paint(x, y, width, height, coding, img_data, packet_sequence, rowstride, options) {
	show("paint("+img_data.length+" bytes of "+("zlib" in options?"zlib ":"")+coding+" data "+width+"x"+height+" at "+x+","+y+")");
	if (coding=="rgb32") {
		//show("options="+(options).toSource());
		if (options!=null && options["zlib"]>0) {
			var inflated = new Zlib.Inflate(img_data).decompress();
			//show("rgb32 data inflated from "+img_data.length+" to "+inflated.length+" bytes");
			img_data = inflated;
		}
		//force set alpha to 1.0
		//for (var a=0; a<width*height; a++) {
		//	img_data[a*4+3] = 255;
		//}
		var data = this.image.data;
		var stride = this.image.width*4;
		if (x==0 && width==this.image.width && y+height<=this.image.height) {
			//take a shortcut: copy all lines
			data.set(img_data, y*stride);
			//show("image updated "+height+" full lines in one go!");
		}
		else {
			//TODO: bounds checking?
			var line;
			var in_stride = width*4;
			for (var i=0; i<height; i++) {
				line = img_data.subarray(i*in_stride, (i+1)*in_stride);
				data.set(line, (y+i)*stride + x*4);
			}
			//show("image updated in "+height+" lines..");
		}
	}
	this.state.invalidate();
};

// Close the window and free all resources
XpraWindow.prototype.destroy = function destroy() {
	if (this.shape!=null) {
		canvas_state.removeShape(this.shape);
		this.shape = null;
	}
};

// Determine if a point is inside the window's contents
XpraWindow.prototype.contains = function(mx, my) {
	"use strict";
	// All we have to do is make sure the Mouse X,Y fall in the area between
	// the shape's X and (X + Height) and its Y and (Y + Height)
	return	(this.x <= mx) && (this.x + this.w >= mx) &&
					(this.y <= my) && (this.y + this.h >= my);
};

XpraWindow.prototype.is_grab_area = function(mx, my) {
	"use strict";
	if (!this.contains(mx, my))
		return false;
	// use window relative values:
	var x = mx - this.x;
	var y = my - this.y;
	// must be in the border area:
	return (y<=this.offsets[0] || my>=(this.h-this.offsets[2]) ||
			x<=this.offsets[3] || x>=(this.w-this.offsets[1]))
};
