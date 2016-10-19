/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2014 Joshua Higgins <josh@kxes.net>
 * Copyright (c) 2015 Spikes, Inc.
 * Licensed under MPL 2.0
 *
 * xpra window
 *
 * Based on shape.js but no longer requires it
 *
 * requires:
 *   jQueryUI
 */

/**
 * This is the class representing a window we draw on the canvas.
 * It has a geometry, it may have borders and a top bar.
 * The contents of the window is an image, which gets updated
 * when we receive pixels from the server.
 */
function XpraWindow(client, canvas_state, wid, x, y, w, h, metadata, override_redirect, client_properties, geometry_cb, mouse_move_cb, mouse_click_cb, set_focus_cb, window_closed_cb, htmldiv) {
	"use strict";
	// use me in jquery callbacks as we lose 'this'
	var me = this;
	this.debug = false;
	// there might be more than one client
	this.client = client;
	//keep reference both the internal canvas and screen drawn canvas:
	this.canvas = canvas_state;
	this.canvas_ctx = this.canvas.getContext('2d');
	this.offscreen_canvas = null;
	this.offscreen_canvas_ctx = null;
	this.offscreen_canvas_mode = null;
	this._init_2d_canvas();

	//enclosing div in page DOM
	this.div = jQuery("#" + String(wid));

	// h264 video stuff
	this.avc = null;
	this.glcanvas = null;

	//callbacks start null until we finish init:
	this.geometry_cb = null;
	this.mouse_move_cb = null;
	this.mouse_click_cb = null;
	this.window_closed_cb = null;

	//xpra specific attributes:
	this.wid = wid;
	this.metadata = {};
	this.override_redirect = override_redirect;
	this.client_properties = client_properties;

	//window attributes:
	this.title = null;
	this.windowtype = null;
	this.fullscreen = false;
	this.saved_geometry = null;
	this.maximized = false;
	this.focused = false;

	//these values represent the internal geometry
	//i.e. geometry as windows appear to the compositor
	this.x = x;
	this.y = y;
	this.w = w;
	this.h = h;

	// last mouse position
	this.last_mouse_x = null;
	this.last_mouse_y = null;

	// get offsets
	this.leftoffset = parseInt(jQuery(this.div).css('border-left-width'), 10);
	this.rightoffset = parseInt(jQuery(this.div).css('border-right-width'), 10);
	this.topoffset = parseInt(jQuery(this.div).css('border-top-width'), 10);
	this.bottomoffset = parseInt(jQuery(this.div).css('border-bottom-width'), 10);

	// Hook up the events we want to receive:
	jQuery(this.canvas).mousedown(function (e) {
		me.on_mousedown(e);
	});
	jQuery(this.canvas).mouseup(function (e) {
		me.on_mouseup(e);
	});
	jQuery(this.canvas).mousemove(function (e) {
		me.on_mousemove(e);
	});

	// now safe to assign the callbacks:
	this.geometry_cb = geometry_cb || null;
	this.mouse_move_cb = mouse_move_cb || null;
	this.mouse_click_cb = mouse_click_cb || null;
	this.window_closed_cb = window_closed_cb || null;

	// update metadata that is safe before window is drawn
	this.update_metadata(metadata, true);

	// create the decoration as part of the window, style is in CSS
	jQuery(this.div).addClass("window");
	jQuery(this.div).addClass("window-" + this.windowtype);
	// add a title bar to this window if we need to
	if((this.windowtype == "NORMAL") || (this.windowtype == "DIALOG") || (this.windowtype == "UTILITY")) {
		if(!this.override_redirect) {
			// create header
			jQuery(this.div).prepend('<div id="head' + String(wid) + '" class="windowhead"> '+
					'<span class="windowicon"><img src="../icons/noicon.png" id="windowicon' + String(wid) + '" /></span> '+
					'<span class="windowtitle" id="title' + String(wid) + '">' + this.title + '</span> '+
					'<span class="windowbuttons"> '+
					'<span id="maximize' + String(wid) + '"><img src="../icons/maximize.png" /></span> '+
					'<span id="close' + String(wid) + '"><img src="../icons/close.png" /></span> '+
					'</span></div>');
			// make draggable
			jQuery(this.div).draggable({
				cancel: "canvas",
				stop: function(e, ui) {
					me.handle_moved(ui);
				}
			});
			// attach resize handles
			jQuery(this.div).resizable({
		      helper: "ui-resizable-helper",
		      stop: function(e, ui) {
		      	me.handle_resized(ui);
		      }
		    });
			this.d_header = '#head' + String(wid);
			this.d_closebtn = '#close' + String(wid);
			this.d_maximizebtn = '#maximize' + String(wid);
			// adjust top offset
			this.topoffset = this.topoffset + parseInt(jQuery(this.d_header).css('height'), 10);
			// assign some interesting callbacks
			jQuery('#head' + String(wid)).click(function() {
				set_focus_cb(me);
			});
			jQuery('#close' + String(wid)).click(function() {
				window_closed_cb(me);
			});
			jQuery('#maximize' + String(wid)).click(function() {
				me.toggle_maximized();
			});
		} else {
			jQuery(this.div).addClass("override-redirect");
		}
	}

	// create the spinner overlay div
	jQuery(this.div).prepend('<div id="spinner'+String(wid)+'" class="spinneroverlay"><div class="spinnermiddle"><div class="spinner"></div></div></div>');
	this.spinnerdiv = jQuery('#spinner'+String(wid));

	// listen for mouse wheel events on my window
	jQuery(this.div).bind('mousewheel DOMMouseScroll', function (e) {
		me.on_mousescroll(e);
	});

	// need to update the CSS geometry
	this.ensure_visible();
	this.updateCSSGeometry();
	//show("placing new window at "+this.x+","+this.y);

	//create the image holding the pixels (the "backing"):
	this.create_image_backing();

	// now read all metadata
	this.update_metadata(metadata);
};

XpraWindow.prototype._init_2d_canvas = function() {
	this.offscreen_canvas_mode = '2d';
	this.offscreen_canvas = document.createElement("canvas");
	this.updateCanvasGeometry();
	this.offscreen_canvas_ctx = this.offscreen_canvas.getContext('2d');
}

XpraWindow.prototype._init_3d_canvas = function() {
	// if we couldn't init the 3d context, we should fall back gracefully!
	this.offscreen_canvas_mode = '3d';
	this.offscreen_canvas = document.createElement("canvas");
	this.updateCanvasGeometry();
	this.offscreen_canvas_ctx = this.offscreen_canvas.getContext('webgl');
}

XpraWindow.prototype.set_spinner = function(state) {
	if(state) {
		this.spinnerdiv.hide();
	} else {
		this.spinnerdiv.css("display", "table");
	}
}

XpraWindow.prototype.ensure_visible = function() {
	var oldx = this.x;
	var oldy = this.y;
	// for now make sure we don't out of top left
	// this will be much smarter!
	if(oldx <= 0) {
		this.x = 0 + this.leftoffset;
	}
	if(oldy <= 10) {
		this.y = 0 + this.topoffset;
	}
	if((oldx != this.x) || (oldy != this.y)) {
		this.updateCSSGeometry();
		return false;
	}
	return true;
}

XpraWindow.prototype.updateCanvasGeometry = function() {
	// set size of both canvas if needed
	if(this.canvas.width != this.w) {
		this.canvas.width = this.w;
	}
	if(this.canvas.height != this.h) {
		this.canvas.height = this.h;
	}
	if(this.offscreen_canvas.width != this.w) {
		this.offscreen_canvas.width = this.w;
	}
	if(this.offscreen_canvas.height != this.h) {
		this.offscreen_canvas.height = this.h;
	}
}

XpraWindow.prototype.updateCSSGeometry = function() {
	// set size of canvas
	this.updateCanvasGeometry();
	// work out outer size
	this.outerH = this.h + this.topoffset + this.bottomoffset;
	this.outerW = this.w + this.leftoffset + this.rightoffset;
	// set width and height
	jQuery(this.div).css('width', this.outerW);
	jQuery(this.div).css('height', this.outerH);
	// set CSS attributes to outerX and outerY
	this.outerX = this.x - this.leftoffset;
	this.outerY = this.y - this.topoffset;
	jQuery(this.div).css('left', this.outerX);
	jQuery(this.div).css('top', this.outerY);
}

XpraWindow.prototype.updateFocus = function() {
	if(this.focused) {
		// set focused style to div
		jQuery(this.div).addClass("windowinfocus");

	} else {
		// set not in focus style
		jQuery(this.div).removeClass("windowinfocus");
	}
}

XpraWindow.prototype.getMouse = function(e) {
	"use strict";

	// get mouse position take into account scroll
	var mx = e.clientX + jQuery(document).scrollLeft();
	var my = e.clientY + jQuery(document).scrollTop();

	// check last mouse position incase the event
	// hasn't provided it - bug #854
	if(isNaN(mx) || isNaN(my)) {
		if(!isNaN(this.last_mouse_x) && !isNaN(this.last_mouse_y)) {
			mx = this.last_mouse_x;
			my = this.last_mouse_y;
		} else {
			// should we avoid sending NaN to the server?
			mx = 0;
			my = 0;
		}
	} else {
		this.last_mouse_x = mx;
		this.last_mouse_y = my;
	}

	var mbutton = 0;
	if ("which" in e)  // Gecko (Firefox), WebKit (Safari/Chrome) & Opera
		mbutton = Math.max(0, e.which);
	else if ("button" in e)  // IE, Opera (zero based)
		mbutton = Math.max(0, e.button)+1;
	//show("getmouse: button="+mbutton+", which="+e.which+", button="+e.button);

	// We return a simple javascript object (a hash) with x and y defined
	return {x: mx, y: my, button: mbutton};
};

XpraWindow.prototype.on_mousemove = function(e) {
	var mouse = this.getMouse(e),
			mx = Math.round(mouse.x),
			my = Math.round(mouse.y);

	var modifiers = [];
	var buttons = [];
	this.handle_mouse_move(mx, my, modifiers, buttons);

};

XpraWindow.prototype.on_mousedown = function(e) {
	var mouse = this.getMouse(e),
			mx = Math.round(mouse.x),
			my = Math.round(mouse.y);

	// pass the click to the area:
	var modifiers = [];
	var buttons = [];
	this.handle_mouse_click(mouse.button, true, mx, my, modifiers, buttons);
	return;
};

XpraWindow.prototype.on_mouseup = function(e) {
	// if not handling it ourselves, pass it down:
	var mouse = this.getMouse(e),
			mx = Math.round(mouse.x),
			my = Math.round(mouse.y);
	if (!this.dragging) {
		var modifiers = [];
		var buttons = [];
		this.handle_mouse_click(mouse.button, false, mx, my, modifiers, buttons);
	}

	this.dragging = false;
};

XpraWindow.prototype.on_mousescroll = function(e) {
	var mouse = this.getMouse(e),
			mx = Math.round(mouse.x),
			my = Math.round(mouse.y);

	var modifiers = [];
	var buttons = [];

	// see if we are going up or down
    if (e.originalEvent.wheelDelta > 0 || e.originalEvent.detail < 0) {
        // scroll up
        this.handle_mouse_click(4, true, mx, my, modifiers, buttons);
        this.handle_mouse_click(4, false, mx, my, modifiers, buttons);
    }
    else {
    	// scroll down
    	this.handle_mouse_click(5, true, mx, my, modifiers, buttons);
        this.handle_mouse_click(5, false, mx, my, modifiers, buttons);
    }
}

/**
 * toString allows us to identify windows by their unique window id.
 */
XpraWindow.prototype.toString = function() {
	"use strict";
	return "Window("+this.wid+")";
};

/**
 * Allocates the image object containing the window's pixels.
 */
XpraWindow.prototype.create_image_backing = function() {
	"use strict";
	var previous_image = this.image;
	var img_geom = this.get_internal_geometry();
	//show("createImageData: "+img_geom.toSource());
	// this should draw to the offscreen canvas
	//this.image = this.offscreen_canvas.getContext('2d').createImageData(img_geom.w, img_geom.h);
	//if (previous_image) {
		//copy previous pixels to new image, ignoring bit gravity
	//	this.offscreen_canvas.getContext('2d').putImageData(previous_image, 0, 0);
	//}

	// this should copy canvas pixel data since a canvas is the backing!
};

/**
 * Update our metadata cache with new key-values,
 * then call set_metadata with these new key-values.
 */
XpraWindow.prototype.update_metadata = function(metadata, safe) {
	"use strict";
	//update our metadata cache with new key-values:
	for (var attrname in metadata) {
		this.metadata[attrname] = metadata[attrname];
	}
	if(safe) {
		this.set_metadata_safe(metadata);
	} else {
    	this.set_metadata(metadata)
    }
};

/**
 * Apply only metadata settings that are safe before window is drawn
 */
XpraWindow.prototype.set_metadata_safe = function(metadata) {
	"use strict";
    if ("title" in metadata) {
    	this.title = metadata["title"];
    	jQuery('#title' + this.wid).html(this.title);
    }
    if ("window-type" in metadata) {
    	this.windowtype = metadata["window-type"][0];
    }
};

/**
 * Apply new metadata settings.
 */
XpraWindow.prototype.set_metadata = function(metadata) {
	"use strict";
    if ("fullscreen" in metadata) {
    	this.set_fullscreen(metadata["fullscreen"]==1);
    }
    if ("maximized" in metadata) {
    	this.set_maximized(metadata["maximized"]==1);
    }
    if ("title" in metadata) {
    	this.title = metadata["title"];
    	jQuery('#title' + this.wid).html(this.title);
    }
    if ("window-type" in metadata) {
    	this.windowtype = metadata["window-type"][0];
    }
};

/**
 * Save the window geometry so we can restore it later
 * (ie: when un-maximizing or un-fullscreening)
 */
XpraWindow.prototype.save_geometry = function() {
	"use strict";

    this.saved_geometry = {
    		"x" : this.x,
    		"y"	: this.y,
    		"w"	: this.w,
    		"h" : this.h};
}
/**
 * Restores the saved geometry (if it exists).
 */
XpraWindow.prototype.restore_geometry = function() {
	"use strict";

	if (this.saved_geometry==null) {
		return;
	}
	this.x = this.saved_geometry["x"];
	this.y = this.saved_geometry["y"];
	this.w = this.saved_geometry["w"];
	this.h = this.saved_geometry["h"];
	// delete saved geometry
	this.saved_geometry = null;
	// then call local resized callback
	this.handle_resized();
};

/**
 * Maximize / unmaximizes the window.
 */
XpraWindow.prototype.set_maximized = function(maximized) {
	"use strict";
	//show("set_maximized("+maximized+")");
	if (this.maximized==maximized) {
		return;
	}
	this.max_save_restore(maximized);
	this.maximized = maximized;
	this.handle_resized();
	// enable or disable the draggable event
	if(this.maximized) {
		jQuery(this.div).draggable('disable');
	} else {
		jQuery(this.div).draggable('enable');
	}
};

/**
 * Toggle maximized state
 */
XpraWindow.prototype.toggle_maximized = function() {
	"use strict";
	//show("set_maximized("+maximized+")");
	if (this.maximized==true) {
		this.set_maximized(false);
	} else {
		this.set_maximized(true);
	}
};

/**
 * Fullscreen / unfullscreen the window.
 */
XpraWindow.prototype.set_fullscreen = function(fullscreen) {
	"use strict";
	/*

	TODO

	//show("set_fullscreen("+fullscreen+")");
	if (this.fullscreen==fullscreen) {
		return;
	}
	this.max_save_restore(fullscreen);
	this.fullscreen = fullscreen;
	this.calculate_offsets();
	this.handle_resize();
	*/
};

/**
 * Either:
 * - save the geometry and use all the space
 * - or restore the geometry
 */
XpraWindow.prototype.max_save_restore = function(use_all_space) {
	"use strict";
	if (use_all_space) {
		this.save_geometry();
		this.fill_screen();
	}
	else {
		this.restore_geometry();
	}
};

/**
 * Use up all the available screen space
 */
XpraWindow.prototype.fill_screen = function() {
	"use strict";
	// should be as simple as this
	// in future we may have a taskbar for minimized windows
	// which should be subtracted from screen size
	var screen_size = this.client._get_desktop_size();
	this.x = 0 + this.leftoffset;
	this.y = 0 + this.topoffset;
	this.w = (screen_size[0] - this.leftoffset) - this.rightoffset;
	this.h = (screen_size[1] - this.topoffset) - this.bottomoffset;
};

XpraWindow.prototype.undecorate = function() {
	// hide the window decoration
	jQuery(this.d_header).hide();
	// replace window style
	jQuery(this.div).removeClass("window");
	jQuery(this.div).addClass("undecorated");
	// reset the offsets
	this.leftoffset = parseInt(jQuery(this.div).css('border-left-width'), 10);
	this.rightoffset = parseInt(jQuery(this.div).css('border-right-width'), 10);
	this.topoffset = parseInt(jQuery(this.div).css('border-top-width'), 10);
	this.bottomoffset = parseInt(jQuery(this.div).css('border-bottom-width'), 10);
	// update geometry
	this.updateCSSGeometry();
}

/**
 * We have resized the window, so we need to:
 * - work out new position of internal canvas
 * - update external CSS position
 * - resize the backing image
 * - fire the geometry_cb
 */
XpraWindow.prototype.handle_resized = function(e) {
	"use strict";
	// this function is called on local resize only,
	// remote resize will call this.resize()
	// need to update the internal geometry
	if(e) {
		this.w = Math.round(e.size.width) - this.leftoffset - this.rightoffset;
		this.h = Math.round(e.size.height) - this.topoffset - this.bottomoffset;
	}
	// then update CSS and redraw backing
	this.updateCSSGeometry();
	this.create_image_backing();
	// send geometry callback
	this.geometry_cb(this);
};

/**
 * Like handle_resized, except we should
 * store internal geometry, external is always in CSS left and top
 */
XpraWindow.prototype.handle_moved = function(e) {
	"use strict";
	// add on padding to the event position so that
	// it reflects the internal geometry of the canvas
	this.x = Math.round(e.position.left) + this.leftoffset;
	this.y = Math.round(e.position.top) + this.topoffset;
	// make sure we are visible after move
	this.ensure_visible();
	// tell remote we have moved window
	this.geometry_cb(this);
}

/**
 * The "screen" has been resized, we may need to resize our window to match
 * if it is fullscreen or maximized.
 */
XpraWindow.prototype.screen_resized = function() {
	"use strict";

	if (this.fullscreen || this.maximized) {
		this.fill_screen();
		this.handle_resized();
	}
};

/**
 * Things ported from original shape
 */

XpraWindow.prototype.move_resize = function(x, y, w, h) {
	"use strict";
	// only do it if actually changed!
	if(!(this.w == w) || !(this.h == h) || !(this.x == x) || !(this.y == y)) {
		this.w = w;
		this.h = h;
		this.x = x;
		this.y = y;
		if(!this.ensure_visible()) {
			// we had to move the window so that it was visible
			// is this the right thing to do?
			this.geometry_cb(this);
		}
		this.updateCSSGeometry();
		this.create_image_backing();
	}
};

XpraWindow.prototype.move = function(x, y) {
	"use strict";
	this.move_resize(x, y, this.w, this.h);
};

XpraWindow.prototype.resize = function(w, h) {
	"use strict";
	this.move_resize(this.x, this.y, w, h);
};

/**
 * Returns the geometry of the window backing image,
 * the inner window geometry (without any borders or top bar).
 */
XpraWindow.prototype.get_internal_geometry = function() {
	"use strict";
	/* we store the internal geometry only
	 * and work out external geometry on the fly whilst
	 * updating CSS
	 */
	return { x : this.x,
			 y : this.y,
			 w : this.w,
			 h : this.h};
};

/**
 * Handle mouse click from this window's canvas,
 * then we fire "mouse_click_cb" (if it is set).
 */
XpraWindow.prototype.handle_mouse_click = function(button, pressed, mx, my, modifiers, buttons) {
	"use strict";
	if (this.debug)
		console.log("got mouse click at ", mx, my)
	// mouse click event is from canvas just for this window so no need to check
	// internal geometry anymore
	this.mouse_click_cb(this, button, pressed, mx, my, modifiers, buttons);
};

/**
 * Handle mouse move from this window's canvas,
 * then we fire "mouse_move_cb" (if it is set).
 */
XpraWindow.prototype.handle_mouse_move = function(mx, my, modifiers, buttons) {
	"use strict";
	this.mouse_move_cb(this, mx, my, modifiers, buttons);
};


XpraWindow.prototype.update_icon = function(width, height, encoding, img_data) {
	"use strict";

	if (encoding=="png") {
		jQuery('#windowicon' + String(this.wid)).attr('src', "data:image/"+encoding+";base64," + this._arrayBufferToBase64(img_data));
	}
};


XpraWindow.prototype.reset_cursor = function() {
	"use strict";
	
	jQuery("#"+String(this.wid)).css("cursor", 'default');
};

XpraWindow.prototype.set_cursor = function(encoding, w, h, img_data) {
	"use strict";

	if (encoding=="png") {
		var cursor_url = "url('data:image/"+encoding+";base64," + window.btoa(img_data) + "'),default";
		jQuery("#"+String(this.wid)).css("cursor", cursor_url);
	}
};



/**
 * This function draws the contents of the off-screen canvas to the visible
 * canvas. However the drawing is requested by requestAnimationFrame which allows
 * the browser to group screen redraws together, and automatically adjusts the
 * framerate e.g if the browser window/tab is not visible.
 */
XpraWindow.prototype.draw = function() {
	"use strict";
	//pass the 'buffer' canvas directly to visible canvas context
	this.canvas_ctx.drawImage(this.offscreen_canvas, 0, 0);
};

XpraWindow.prototype._arrayBufferToBase64 = function(uintArray) {
    // apply in chunks of 10400 to avoid call stack overflow
    // https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Function/apply
    var s = "";
    var skip = 10400;
    if (uintArray.subarray) {
        for (var i=0, len=uintArray.length; i<len; i+=skip) {
            s += String.fromCharCode.apply(null, uintArray.subarray(i, Math.min(i + skip, len)));
        }
    } else {
        for (var i=0, len=uintArray.length; i<len; i+=skip) {
            s += String.fromCharCode.apply(null, uintArray.slice(i, Math.min(i + skip, len)));
        }
    }
    return window.btoa(s);
}

/**
 * The following function inits the h264 decoder
 */
XpraWindow.prototype._init_avc = function() {
	var me = this;
	// configure the AVC decoder
	this.avc = new Decoder({
		rgb: true
	});
    this.avc.onPictureDecoded = function(buffer, bufWidth, bufHeight) {
        var img = me.offscreen_canvas_ctx.createImageData(bufWidth, bufHeight);
        img.data.set(buffer);
		me.offscreen_canvas_ctx.putImageData(img, 0, 0);
    };
};


/**
 * Updates the window image with new pixel data
 * we have received from the server.
 * The image is painted into off-screen canvas.
 */
XpraWindow.prototype.paint = function paint(x, y, width, height, coding, img_data, packet_sequence, rowstride, options, decode_callback) {
	"use strict";
 	if (this.debug)
 		console.log("paint("+img_data.length+" bytes of "+("zlib" in options?"zlib ":"")+coding+" data "+width+"x"+height+" at "+x+","+y+") focused="+this.focused);

	if (coding=="rgb32") {
		// create image data
		if(this.offscreen_canvas_mode!='2d') {
	    	this._init_2d_canvas();
	    }
		var img = this.offscreen_canvas_ctx.createImageData(width, height);
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
		} else if (options!=null && options["lz4"]>0) {
			// in future we need to make sure that we use typed arrays everywhere...
			if(img_data.subarray) {
				var d = img_data.subarray(0, 4);
			} else {
				var d = img_data.slice(0, 4);
			}
			// will always be little endian
			var length = d[0] | (d[1] << 8) | (d[2] << 16) | (d[3] << 24);
			// decode the LZ4 block
			var inflated = new Buffer(length);
			if(img_data.subarray) {
				var uncompressedSize = LZ4.decodeBlock(img_data.subarray(4), inflated);
			} else {
				var uncompressedSize = LZ4.decodeBlock(img_data.slice(4), inflated);
			}
			img_data = inflated.slice(0, uncompressedSize);
		}
		// set the imagedata rgb32 method
		if(img_data.length > img.data.length) {
			console.error("data size mismatch: wanted",img.data.length,", got",img_data.length, ", stride",rowstride);
		} else {
			if (this.debug)
				console.log("got ",img_data.length,"to paint with stride",rowstride);
		}
		img.data.set(img_data);
		this.offscreen_canvas_ctx.putImageData(img, x, y);
		// send decode callback once we actually decoded
		decode_callback(this.client);
	}
	else if (coding=="jpeg" || coding=="png") {
		// create image data
		if(this.offscreen_canvas_mode!='2d') {
	    	this._init_2d_canvas();
	    }
		var img = this.offscreen_canvas_ctx.createImageData(width, height);
		// decode image
		var j = new Image();
		j.src = "data:image/"+coding+";base64," + this._arrayBufferToBase64(img_data);
		var me = this;
	    j.onload = function () {
	        me.offscreen_canvas_ctx.drawImage(j, x, y);
	        // send decode callback once we actually decoded
			decode_callback(me.client);
	    };
	}
	else if (coding=="h264") {
		if(!this.avc) {
			this._init_avc();
		}
		// we can pass a buffer full of NALs to avc.decode directly
		// as long as they are framed properly with the NAL header
		this.avc.decode(new Uint8Array(img_data));
		// how do we know when the avc has finished decoding?!
		decode_callback(this.client);
		//this._h264_process_raw(img_data);
	}
	else {
		throw "unsupported coding " + coding;
	}
};

/**
 * Close the window and free all resources
 */
XpraWindow.prototype.destroy = function destroy() {
	"use strict";
	// remove div
	this.div.remove()
};
