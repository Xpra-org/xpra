/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Licensed under MPL 2.0
 *
 * xpra window
 *
 * Based on shape.js
 */

/**
 * This is the class representing a window we draw on the canvas.
 * It has a geometry, it may have borders and a top bar.
 * The contents of the window is an image, which gets updated
 * when we receive pixels from the server.
 */
function XpraWindow(canvas_state, wid, x, y, w, h, metadata, override_redirect, client_properties,
		geometry_cb, mouse_move_cb, mouse_click_cb) {
	"use strict";
	//keep reference to the canvas:
	this.state = canvas_state;
	//callbacks start null until we finish init:
	this.geometry_cb = null;
	this.mouse_move_cb = null;
	this.mouse_click_cb = null;

	//styling:
	this.borderColor = '#101028';
	this.topBarColor = '#A8A8B0';

	//the window "backing":
	this.image = null;

	//xpra specific attributes:
	this.wid = wid;
	this.metadata = {};
	this.override_redirect = override_redirect;
	this.client_properties = client_properties;

	//window attributes:
	this.title = null;
	this.fullscreen = false;
	this.saved_geometry = null;
	this.maximized = false;
	this.focused = false;

	//not the real geometry we will use,
	//but enough to avoid errors if update_metadata fires changes
	this.x = x;
	this.y = y;
	this.w = w;
	this.h = h;

	this.update_metadata(metadata);

	// the space taken by window decorations:
	this.calculate_offsets();

	if (!this.fullscreen && !this.maximized) {
		// if fullscreen or maximized, the metadata update will have set the new size already
		// account for borders, and try to make the image area map to (x,y):
		var rx = (x || 0) - this.borderWidth;
		var ry = (y || 0) - this.topBarHeight + this.borderWidth;
		var rw = (w || 1) + this.borderWidth*2;
		var rh = (h || 1) + this.borderWidth*2 + this.topBarHeight;
		this.move_resize(rx, ry, rw, rh);
		//show("after move resize: ("+this.w+", "+this.h+")");
	}

	// now safe to assign the callbacks:
	this.geometry_cb = geometry_cb || null;
	this.mouse_move_cb = mouse_move_cb || null;
	this.mouse_click_cb = mouse_click_cb || null;

	//create the image holding the pixels (the "backing"):
	this.create_image_backing();
	canvas_state.addShape(this);
};

/**
 * toString allows us to identify windows by their unique window id.
 */
XpraWindow.prototype.toString = function() {
	return "Window("+this.wid+")";
};

/**
 * Allocates the image object containing the window's pixels.
 */
XpraWindow.prototype.create_image_backing = function() {
	var previous_image = this.image;
	var img_geom = this.get_internal_geometry();
	//show("createImageData: "+img_geom.toSource());
	this.image = canvas_state.canvas.getContext('2d').createImageData(img_geom.w, img_geom.h);
	if (previous_image) {
		//copy previous pixels to new image, ignoring bit gravity
		//TODO!
	}
};

/**
 * Depending on the type of window (OR, fullscreen)
 * we calculate the offsets from the edge of the window
 * to the contents of the window.
 */
XpraWindow.prototype.calculate_offsets = function() {
	if (this.override_redirect || this.fullscreen) {
		//no borders or top bar at all:
		this.borderWidth = 0;
		this.topBarHeight = 0;
	}
	else {
		//regular borders and top bar:
		this.borderWidth = 2;
		this.topBarHeight = 20;
	}
	this.offsets = [this.borderWidth+this.topBarHeight, this.borderWidth, this.borderWidth, this.borderWidth];
};

/**
 * Update our metadata cache with new key-values,
 * then call set_metadata with these new key-values.
 */
XpraWindow.prototype.update_metadata = function(metadata) {
	//update our metadata cache with new key-values:
	for (var attrname in metadata) {
		this.metadata[attrname] = metadata[attrname];
	}
    this.set_metadata(metadata)
};

/**
 * Apply new metadata settings.
 */
XpraWindow.prototype.set_metadata = function(metadata) {
    if ("fullscreen" in metadata) {
    	this.set_fullscreen(metadata["fullscreen"]==1);
    }
    if ("maximized" in metadata) {
    	this.set_maximized(metadata["maximized"]==1);
    }
    if ("title" in metadata) {
    	this.title = metadata["title"];
    }
};

/**
 * Save the window geometry so we can restore it later
 * (ie: when un-maximizing or un-fullscreening)
 */
XpraWindow.prototype.save_geometry = function() {
	if (this.x==undefined || this.y==undefined)
		return;
    this.saved_geometry = {
    		"x" : this.x,
    		"y"	: this.y,
    		"w"	: this.w,
    		"h" : this.h,
    		"maximized"	: this.maximized,
    		"fullscreen" : this.fullscreen};
}
/**
 * Restores the saved geometry (if it exists).
 */
XpraWindow.prototype.restore_geometry = function() {
	if (this.saved_geometry==null) {
		return;
	}
	this.x = this.saved_geometry["x"];
	this.y = this.saved_geometry["y"];
	this.w = this.saved_geometry["w"];
	this.h = this.saved_geometry["h"];
	this.maximized = this.saved_geometry["maximized"];
	this.fullscreen = this.saved_geometry["fullscreen"];
};

/**
 * Maximize / unmaximizes the window.
 */
XpraWindow.prototype.set_maximized = function(maximized) {
	//show("set_maximized("+maximized+")");
	if (this.maximized==maximized) {
		return;
	}
	this.max_save_restore(maximized);
	this.maximized = maximized;
	this.calculate_offsets();
	this.handle_resize();
};
/**
 * Fullscreen / unfullscreen the window.
 */
XpraWindow.prototype.set_fullscreen = function(fullscreen) {
	//show("set_fullscreen("+fullscreen+")");
	if (this.fullscreen==fullscreen) {
		return;
	}
	this.max_save_restore(fullscreen);
	this.fullscreen = fullscreen;
	this.calculate_offsets();
	this.handle_resize();
};

/**
 * Either:
 * - save the geometry and use all the space
 * - or restore the geometry
 */
XpraWindow.prototype.max_save_restore = function(use_all_space) {
	if (use_all_space) {
		this.save_geometry();
		this.fill_canvas();
	}
	else {
		this.restore_geometry();
	}
};

/**
 * Use up all the canvas space
 */
XpraWindow.prototype.fill_canvas = function() {
	this.x = 0;
	this.y = 0;
	this.w = this.state.width;
	this.h = this.state.height;
};

/**
 * We have resized the window, so we need to:
 * - resize the backing image
 * - tell the canvas to repaint us
 * - fire the geometry_cb
 */
XpraWindow.prototype.handle_resize = function() {
	this.create_image_backing();
	this.state.invalidate();
	if (this.geometry_cb!=null) {
		this.geometry_cb(this);
	}
};

/**
 * The canvas ("screen") has been resized, we may need to resize our window to match
 * if it is fullscreen or maximized.
 */
XpraWindow.prototype.canvas_resized = function() {
	if (this.fullscreen || this.maximized) {
		this.fill_canvas();
		this.handle_resize();
	}
};

XpraWindow.prototype.move_resize = Shape.prototype.move_resize;
XpraWindow.prototype.move = Shape.prototype.move;
XpraWindow.prototype.resize = Shape.prototype.resize;
XpraWindow.prototype.get_window_geometry = Shape.prototype.get_window_geometry;

/**
 * Returns the geometry of the window backing image,
 * the inner window geometry (without any borders or top bar).
 */
XpraWindow.prototype.get_internal_geometry = function(ctx) {
	"use strict";
	// This should always be true:
	//this.image.width = this.w - this.borderWidth*2;
	//this.image.height = this.h - (this.borderWidth*2 + this.topBarHeight);
	return { x : this.x+this.borderWidth,
			 y : this.y+this.borderWidth+this.topBarHeight,
			 w : this.w - this.borderWidth*2,
			 h : this.h - (this.borderWidth*2 + this.topBarHeight)};
};

/**
 * If the click is in the "internal_geometry" (see above),
 * then we fire "mouse_click_cb" (if it is set).
 */
XpraWindow.prototype.handle_mouse_click = function(button, pressed, mx, my, modifiers, buttons) {
	"use strict";
	var igeom = this.get_internal_geometry();
	if (this.mouse_click_cb!=null && rectangle_contains(igeom, mx, my)) {
		this.mouse_click_cb(this, button, pressed, mx, my, modifiers, buttons);
	}
};

/**
 * If the click is in the "internal_geometry" (see above),
 * then we fire "mouse_move_cb" (if it is set).
 */
XpraWindow.prototype.handle_mouse_move = function(mx, my, modifiers, buttons) {
	"use strict";
	var igeom = this.get_internal_geometry();
	if (this.mouse_move_cb!=null && rectangle_contains(igeom, mx, my)) {
		this.mouse_move_cb(this, mx, my, modifiers, buttons);
	}
};

/**
 * Draws this window to the given context:
 * - draw the window frame (if not an OR window and not fullscreen)
 * - draw the backing image (the window pixels)
 * - draw selection borders (if the window is the one currently selected)
 */
XpraWindow.prototype.draw = function(ctx) {
	"use strict";

	if (!this.override_redirect && !this.fullscreen) {
		//draw window frame:
		this.draw_frame(ctx);
	}

	//draw the window pixels:
	ctx.putImageData(this.image, this.x + this.borderWidth, this.y + this.borderWidth + this.topBarHeight);

	if (this.state.selection === this && !this.override_redirect) {
		//window.alert("Shape.prototype.draw_selection="+Shape.prototype.draw_selection);
		this.draw_selection(ctx);
	}
};

/**
 * Draws the window frame:
 * a simple rectangle around the edge.
 */
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


/**
 * Draws border and selection rectangles
 * which indicate that the window is selected
 */
XpraWindow.prototype.draw_selection = function(ctx) {
	"use strict";
	if (this.maximized || this.fullscreen) {
		return;
	}
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

/**
 * Updates the window image with new pixel data
 * we have received from the server.
 */
XpraWindow.prototype.paint = function paint(x, y, width, height, coding, img_data, packet_sequence, rowstride, options) {
	"use strict";
	//show("paint("+img_data.length+" bytes of "+("zlib" in options?"zlib ":"")+coding+" data "+width+"x"+height+" at "+x+","+y+") focused="+this.focused);
	if (coding!="rgb32")
		throw Exception("invalid encoding: "+coding);

	//if the pixel data is not in an array buffer already, convert it:
	//(this happens with inlined pixel data)
	if (typeof img_data==='string') {
		var uint = new Uint8Array(img_data.length);
		for(var i=0,j=img_data.length;i<j;++i) {
			uint[i] = img_data.charCodeAt(i);
		}
		img_data = uint;
	}
	//show("options="+(options).toSource());
	if (options!=null && options["zlib"]>0) {
		//show("decompressing "+img_data.length+" bytes of "+coding+"/zlib");
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
	//and we can paint the canvas with it
	//(if we have transparency, we should probably repaint what is underneath...)
	var ctx = this.state.ctx;

	if (x==0 && width==this.image.width && y+height<=this.image.height) {
		//take a shortcut: copy all lines
		data.set(img_data, y*stride);

		if (this.focused) {
			//shortcut: paint canvas directly
			ctx.putImageData(this.image, this.x + this.borderWidth, this.y + this.borderWidth + this.topBarHeight);
			return;
		}
	}
	else if (x+width<=this.image.width && y+height<=this.image.height) {
		var line;
		var in_stride = width*4;

		for (var i=0; i<height; i++) {
			line = img_data.subarray(i*in_stride, (i+1)*in_stride);
			data.set(line, (y+i)*stride + x*4);
		}
		var img = ctx.createImageData(width, height);
		img.data.set(img_data);

		if (this.focused) {
			//shortcut: paint canvas directly
			ctx.putImageData(img, this.x + this.borderWidth + x, this.y + this.borderWidth + this.topBarHeight + y);
			return;
		}
	}
	else {
		//no action taken, no need to invalidate
		return;
	}
	this.state.invalidate();
};

/**
 * Close the window and free all resources
 */
XpraWindow.prototype.destroy = function destroy() {
	"use strict";
	if (this.state!=null) {
		this.state.removeShape(this);
		this.state = null;
	}
};

/**
 * Determine if a point is inside the window's contents
 */
XpraWindow.prototype.contains = function(mx, my) {
	"use strict";
	// All we have to do is make sure the Mouse X,Y fall in the area between
	// the shape's X and (X + Height) and its Y and (Y + Height)
	return	(this.x <= mx) && (this.x + this.w >= mx) &&
					(this.y <= my) && (this.y + this.h >= my);
};

/**
 * Determine if a point is inside the window's grab area.
 * (the edges that are not part of the image backing)
 */
XpraWindow.prototype.is_grab_area = function(mx, my) {
	"use strict";
	if (!this.contains(mx, my)) {
		return false;
	}
	// use window relative values:
	var x = mx - this.x;
	var y = my - this.y;
	// must be in the border area:
	return (y<=this.offsets[0] || my>=(this.h-this.offsets[2]) ||
			x<=this.offsets[3] || x>=(this.w-this.offsets[1]))
};
