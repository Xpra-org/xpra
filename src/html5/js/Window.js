/*
 * Copyright (c) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2014 Joshua Higgins <josh@kxes.net>
 * Copyright (c) 2015-2016 Spikes, Inc.
 * Licensed under MPL 2.0
 *
 * xpra window
 *
 * Based on shape.js but no longer requires it
 *
 * requires:
 *   jQueryUI
 */

"use strict";

/**
 * This is the class representing a window we draw on the canvas.
 * It has a geometry, it may have borders and a top bar.
 * The contents of the window is an image, which gets updated
 * when we receive pixels from the server.
 */
function XpraWindow(client, canvas_state, wid, x, y, w, h, metadata, override_redirect, client_properties, geometry_cb, mouse_move_cb, mouse_click_cb, set_focus_cb, window_closed_cb, htmldiv) {
	// use me in jquery callbacks as we lose 'this'
	var me = this;
	this.debug = false;
	// there might be more than one client
	this.client = client;
	this.log = function() { client.log.apply(client, arguments); };
	this.warn = function() { client.warn.apply(client, arguments); };
	this.error = function() { client.error.apply(client, arguments); };
	//keep reference both the internal canvas and screen drawn canvas:
	this.canvas = canvas_state;
	this.canvas_ctx = this.canvas.getContext('2d');
	this.offscreen_canvas = null;
	this.offscreen_canvas_ctx = null;
	this.offscreen_canvas_mode = null;
	this._init_2d_canvas();
	this.paint_queue = [];
	this.paint_pending = false;

	//enclosing div in page DOM
	this.div = jQuery("#" + String(wid));

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
	this.decorations = true;
	this.resizable = false;
	this.stacking_layer = 0;

	//these values represent the internal geometry
	//i.e. geometry as windows appear to the compositor
	this.x = x;
	this.y = y;
	this.w = w;
	this.h = h;

	// last mouse position
	this.last_mouse_x = null;
	this.last_mouse_y = null;
	// wheel accumulators:
	this.wheel_delta_x = 0;
	this.wheel_delta_y = 0;

	// get offsets
	this.leftoffset = parseInt(jQuery(this.div).css('border-left-width'), 10);
	this.rightoffset = parseInt(jQuery(this.div).css('border-right-width'), 10);
	this.topoffset = parseInt(jQuery(this.div).css('border-top-width'), 10);
	this.bottomoffset = parseInt(jQuery(this.div).css('border-bottom-width'), 10);

	this.mousedown_event = null;
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
	if (this.windowtype) {
		jQuery(this.div).addClass("window-" + this.windowtype);
	}

	if(this.override_redirect) {
		jQuery(this.div).addClass("override-redirect");
	}
	else if((this.windowtype == "") || (this.windowtype == "NORMAL") || (this.windowtype == "DIALOG") || (this.windowtype == "UTILITY")) {
		this.resizable = true;
		// add a title bar to this window if we need to
		// create header
		jQuery(this.div).prepend('<div id="head' + String(wid) + '" class="windowhead"> '+
				'<span class="windowicon"><img src="../icons/noicon.png" id="windowicon' + String(wid) + '" /></span> '+
				'<span class="windowtitle" id="title' + String(wid) + '">' + this.title + '</span> '+
				'<span class="windowbuttons"> '+
				'<span id="maximize' + String(wid) + '"><img src="../icons/maximize.png" /></span> '+
				'<span id="close' + String(wid) + '"><img src="../icons/close.png" /></span> '+
				'</span></div>');
		// make draggable
		jQuery(this.div).draggable({ cancel: "canvas" });
		jQuery(this.div).on("dragstop",function(ev,ui){
			me.handle_moved(ui);
		});
		// attach resize handles
		jQuery(this.div).resizable({ helper: "ui-resizable-helper", "handles": "n, e, s, w, ne, se, sw, nw" });
		//jQuery(this.div).on("resize",jQuery.debounce(50, function(ev,ui) {
		//  	me.handle_resized(ui);
		//}));
		jQuery(this.div).on("resizestop",function(ev,ui){
		  	me.handle_resized(ui);
		});
		this.d_header = '#head' + String(wid);
		this.d_closebtn = '#close' + String(wid);
		this.d_maximizebtn = '#maximize' + String(wid);
		// adjust top offset
		this.topoffset = this.topoffset + parseInt(jQuery(this.d_header).css('height'), 10);
		// assign some interesting callbacks
		jQuery(this.d_header).click(function() {
			set_focus_cb(me);
		});
		jQuery(this.d_closebtn).click(function() {
			window_closed_cb(me);
		});
		jQuery(this.d_maximizebtn).click(function() {
			me.toggle_maximized();
		});
	}

	// create the spinner overlay div
	jQuery(this.div).prepend('<div id="spinner'+String(wid)+'" class="spinneroverlay"><div class="spinnermiddle"><div class="spinner"></div></div></div>');
	this.spinnerdiv = jQuery('#spinner'+String(wid));

	// listen for mouse wheel events on my window
	var div = document.getElementById(wid);
	function on_mousescroll(e) {
		me.on_mousescroll(e);
	}
	if (Utilities.isEventSupported("wheel")) {
		div.addEventListener('wheel',			on_mousescroll, false);
	}
	else if (Utilities.isEventSupported("mousewheel")) {
		div.addEventListener('mousewheel',		on_mousescroll, false);
	}
	else if (Utilities.isEventSupported("DOMMouseScroll")) {
		div.addEventListener('DOMMouseScroll',	on_mousescroll, false); // for Firefox
	}

	// need to update the CSS geometry
	this.ensure_visible();
	this.updateCSSGeometry();
	//show("placing new window at "+this.x+","+this.y);

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
	var min_visible = 10;
	var desktop_size = this.client._get_desktop_size();
	var ww = desktop_size[0];
	var wh = desktop_size[1];
	//this.log("x=", this.x, "y=", this.y, "w=", this.w, "h=", this.h, "leftoffset=", this.leftoffset, "topoffset=", this.topoffset, " - ww=", ww, "wh=", wh);
	if(oldx + this.w <= min_visible) {
		this.x = min_visible - this.w + this.leftoffset;
	}
	else if (oldx >= ww - min_visible) {
		this.x = Math.min(oldx, ww - min_visible);
	}
	if(oldy <= min_visible) {
		this.y = 0 + this.topoffset;
	}
	else if (oldy >= wh - min_visible) {
		this.y = Math.min(oldy, wh - min_visible);
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
	this.mousedown_event = e;
	var me = this;
	setTimeout(function() {
		me.handle_mouse_click(mouse.button, true, mx, my, modifiers, buttons);
	}, 0);
};

XpraWindow.prototype.on_mouseup = function(e) {
	// if not handling it ourselves, pass it down:
	var mouse = this.getMouse(e),
			mx = Math.round(mouse.x),
			my = Math.round(mouse.y);
	var modifiers = [];
	var buttons = [];
	this.mousedown_event = null;
	var me = this;
	setTimeout(function() {
		me.handle_mouse_click(mouse.button, false, mx, my, modifiers, buttons);
	}, 0);
};

XpraWindow.prototype.on_mousescroll = function(e) {
	var mouse = this.getMouse(e),
			mx = Math.round(mouse.x),
			my = Math.round(mouse.y);
	var modifiers = [];
	var buttons = [];
	var wheel = Utilities.normalizeWheel(e);
	if (this.debug) {
		console.debug("normalized wheel event:", wheel);
	}
	//clamp to prevent event floods:
	var px = Math.min(1200, wheel.pixelX);
	var py = Math.min(1200, wheel.pixelY);
	var apx = Math.abs(px);
	var apy = Math.abs(py);
	//generate a single event if we can, or add to accumulators:
	if (apx>=40 && apx<=160) {
		this.wheel_delta_x = (px>0) ? 120 : -120;
	}
	else {
		this.wheel_delta_x += px;
	}
	if (apy>=40 && apy<=160) {
		this.wheel_delta_y = (py>0) ? 120 : -120;
	}
	else {
		this.wheel_delta_y += py;
	}
	//send synthetic click+release as many times as needed:
	var wx = Math.abs(this.wheel_delta_x);
	var wy = Math.abs(this.wheel_delta_y);
	var btn_x = (this.wheel_delta_x>=0) ? 6 : 7;
	var btn_y = (this.wheel_delta_y>=0) ? 5 : 4;
	while (wx>=120) {
		wx -= 120;
		this.handle_mouse_click(btn_x, true, mx, my, modifiers, buttons);
		this.handle_mouse_click(btn_x, false, mx, my, modifiers, buttons);
	}
	while (wy>=120) {
		wy -= 120;
		this.handle_mouse_click(btn_y, true, mx, my, modifiers, buttons);
		this.handle_mouse_click(btn_y, false, mx, my, modifiers, buttons);
	}
	//store left overs:
	this.wheel_delta_x = (this.wheel_delta_x>=0) ? wx : -wx;
	this.wheel_delta_y = (this.wheel_delta_y>=0) ? wy : -wy;
}

/**
 * toString allows us to identify windows by their unique window id.
 */
XpraWindow.prototype.toString = function() {
	return "Window("+this.wid+")";
};


XpraWindow.prototype.update_zindex = function() {
	var z = 5000 + this.stacking_layer;
	if (this.override_redirect) {
		z = 15000;
	}
	else if (this.windowtype=="DROPDOWN" || this.windowtype=="TOOLTIP" ||
			this.windowtype=="POPUP_MENU" || this.windowtype=="MENU" ||
			this.windowtype=="COMBO") {
		z = 20000;
	}
	else if (this.windowtype=="UTILITY" || this.windowtype=="DIALOG") {
		z = 15000;
	}
	var above = this.metadata["above"];
	if (above) {
		z += 5000;
	}
	else {
		var below = this.metadata["below"];
		if (below) {
			z -= 5000;
		}
	}
	if (this.focused) {
		z += 2500;
	}
	jQuery(this.div).css('z-index', z);
}


/**
 * Update our metadata cache with new key-values,
 * then call set_metadata with these new key-values.
 */
XpraWindow.prototype.update_metadata = function(metadata, safe) {
	//update our metadata cache with new key-values:
	if (this.debug) {
		console.debug("update_metadata(", metadata, ")");
	}
	for (var attrname in metadata) {
		this.metadata[attrname] = metadata[attrname];
	}
	if(safe) {
		this.set_metadata_safe(metadata);
	} else {
		this.set_metadata(metadata)
	}
	this.update_zindex();
};

/**
 * Apply only metadata settings that are safe before window is drawn
 */
XpraWindow.prototype.set_metadata_safe = function(metadata) {
	if ("title" in metadata) {
		this.title = metadata["title"];
		jQuery('#title' + this.wid).html(decodeURIComponent(escape(this.title)));
	}
	if ("window-type" in metadata) {
		this.windowtype = metadata["window-type"][0];
	}
	if ("decorations" in metadata) {
		this.decorations = metadata["decorations"];
		this._set_decorated(this.decorations);
		this.updateCSSGeometry();
		this.handle_resized();
		this.apply_size_constraints();
	}
	if ("opacity" in metadata) {
		var opacity = metadata["opacity"];
		if (opacity<0) {
			opacity = 1.0;
		}
		else {
			opacity = opacity / 0x100000000
		}
		jQuery(this.div).css('opacity', ''+opacity);
	}
	//if the attribute is set, add the corresponding css class:
	var attrs = ["modal", "above", "below"];
	for (var i = 0; i < attrs.length; i++) {
		var attr = attrs[i];
		if (attr in metadata) {
			var value = metadata[attr];
			if (value) {
				jQuery(this.div).addClass(attr);
			}
			else {
				jQuery(this.div).removeClass(attr);
			}
		}
	}
	if (this.resizable && "size-constraints" in metadata) {
		this.apply_size_constraints();
	}
	if ("class-instance" in metadata) {
		var wm_class = metadata["class-instance"];
		var classes = jQuery(this.div).prop("classList");
		if (classes) {
			//remove any existing "wmclass-" classes not in the new wm_class list:
			for (var i = 0; i < classes.length; i++) {
				var _class = classes[i];
				if (_class.startsWith("wmclass-") && wm_class && wm_class.indexOf(_class)<0) {
					jQuery(this.div).removeClass(_class);
				}
			}
		}
		if (wm_class) {
			//add new wm-class:
			for (var i = 0; i < wm_class.length; i++) {
				var _class = wm_class[i].replace(/[^0-9a-zA-Z]/g, '');
				if (_class && !jQuery(this.div).hasClass(_class)) {
					jQuery(this.div).addClass("wmclass-"+_class);
				}
			}
		}
	}
};

XpraWindow.prototype.apply_size_constraints = function() {
	var size_constraints = this.metadata["size-constraints"];
	if (this.maximized) {
		jQuery(this.div).draggable('disable');
	}
	else {
		jQuery(this.div).draggable('enable');
	}
	var hdec = 0, wdec = 0;
	if (this.decorations) {
		//adjust for header
		hdec = jQuery('#head' + this.wid).outerHeight(true);
	}
	var min_size = null, max_size = null;
	if (size_constraints) {
		min_size = size_constraints["minimum-size"];
		max_size = size_constraints["maximum-size"];
	}
	var minw=null, minh=null;
	if (min_size) {
		minw = min_size[0]+wdec;
		minh = min_size[1]+hdec;
	}
	var maxw=null, maxh=null;
	if (max_size) {
		maxw = max_size[0]+wdec;
		maxh = max_size[1]+hdec;
	}
	if(minw>0 && minw==maxw && minh>0 && minh==maxh) {
		jQuery(this.d_maximizebtn).hide();
		jQuery(this.div).resizable('disable');
	} else {
		jQuery(this.d_maximizebtn).show();
		if (!this.maximized) {
			jQuery(this.div).resizable('enable');
		}
		else {
			jQuery(this.div).resizable('disable');
		}
	}
	if (!this.maximized) {
		jQuery(this.div).resizable("option", "minWidth", minw);
		jQuery(this.div).resizable("option", "minHeight", minh);
		jQuery(this.div).resizable("option", "maxWidth", maxw);
		jQuery(this.div).resizable("option", "maxHeight", maxh);
	}
	//TODO: aspectRatio, grid
}


/**
 * Apply new metadata settings.
 */
XpraWindow.prototype.set_metadata = function(metadata) {
	this.set_metadata_safe(metadata);
	if ("fullscreen" in metadata) {
		this.set_fullscreen(metadata["fullscreen"]==1);
	}
	if ("maximized" in metadata) {
		this.set_maximized(metadata["maximized"]==1);
	}
};

/**
 * Save the window geometry so we can restore it later
 * (ie: when un-maximizing or un-fullscreening)
 */
XpraWindow.prototype.save_geometry = function() {
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
	if (this.maximized==maximized) {
		return;
	}
	this.max_save_restore(maximized);
	this.maximized = maximized;
	this.handle_resized();
	// this will take care of disabling the "draggable" code:
	this.apply_size_constraints();
};

/**
 * Toggle maximized state
 */
XpraWindow.prototype.toggle_maximized = function() {
	this.set_maximized(!this.maximized);
};

/**
 * Fullscreen / unfullscreen the window.
 */
XpraWindow.prototype.set_fullscreen = function(fullscreen) {
	if (this.fullscreen==fullscreen) {
		return;
	}
	if (this.resizable) {
		if (fullscreen) {
			this._set_decorated(false);
		}
		else {
			this._set_decorated(this.decorations);
		}
	}
	this.max_save_restore(fullscreen);
	this.fullscreen = fullscreen;
	this.updateCSSGeometry();
	this.handle_resized();
};


XpraWindow.prototype._set_decorated = function(decorated) {
	this.topoffset = parseInt(jQuery(this.div).css('border-top-width'), 10);
	if (decorated) {
		jQuery('#head' + this.wid).show();
		jQuery(this.div).removeClass("undecorated");
		jQuery(this.div).addClass("window");
		this.topoffset = this.topoffset + parseInt(jQuery(this.d_header).css('height'), 10);
	}
	else {
		jQuery('#head' + this.wid).hide();
		jQuery(this.div).removeClass("window");
		jQuery(this.div).addClass("undecorated");
	}
}

/**
 * Either:
 * - save the geometry and use all the space
 * - or restore the geometry
 */
XpraWindow.prototype.max_save_restore = function(use_all_space) {
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
	// should be as simple as this
	// in future we may have a taskbar for minimized windows
	// which should be subtracted from screen size
	var screen_size = this.client._get_desktop_size();
	this.x = 0 + this.leftoffset;
	this.y = 0 + this.topoffset;
	this.w = (screen_size[0] - this.leftoffset) - this.rightoffset;
	this.h = (screen_size[1] - this.topoffset) - this.bottomoffset;
};


/**
 * We have resized the window, so we need to:
 * - work out new position of internal canvas
 * - update external CSS position
 * - resize the backing image
 * - fire the geometry_cb
 */
XpraWindow.prototype.handle_resized = function(e) {
	// this function is called on local resize only,
	// remote resize will call this.resize()
	// need to update the internal geometry
	if(e) {
		this.x = this.x + Math.round(e.position.left - e.originalPosition.left);
		this.y = this.y + Math.round(e.position.top - e.originalPosition.top);
		this.w = Math.round(e.size.width) - this.leftoffset - this.rightoffset;
		this.h = Math.round(e.size.height) - this.topoffset - this.bottomoffset;
	}
	// then update CSS and redraw backing
	this.updateCSSGeometry();
	// send geometry callback
	this.geometry_cb(this);
};

/**
 * Like handle_resized, except we should
 * store internal geometry, external is always in CSS left and top
 */
XpraWindow.prototype.handle_moved = function(e) {
	// add on padding to the event position so that
	// it reflects the internal geometry of the canvas
	//this.log("handle moved: position=", e.position.left, e.position.top);
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
	if (this.fullscreen || this.maximized) {
		this.fill_screen();
		this.handle_resized();
	}
	this.ensure_visible();
};

/**
 * Things ported from original shape
 */

XpraWindow.prototype.move_resize = function(x, y, w, h) {
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
	}
};

XpraWindow.prototype.move = function(x, y) {
	this.move_resize(x, y, this.w, this.h);
};

XpraWindow.prototype.resize = function(w, h) {
	this.move_resize(this.x, this.y, w, h);
};

XpraWindow.prototype.initiate_moveresize = function(x_root, y_root, direction, button, source_indication) {
	var dir_str = MOVERESIZE_DIRECTION_STRING[direction];
	this.log("initiate_moveresize", dir_str, [x_root, y_root, direction, button, source_indication]);
	if (direction==MOVERESIZE_MOVE) {
		var e = this.mousedown_event;
		e.type = "mousedown.draggable";
		e.target = this.div[0];
		this.div.trigger(e);
		//jQuery(this.div).trigger("mousedown");
	}
	else if (direction==MOVERESIZE_CANCEL) {
		jQuery(this.div).draggable('disable');
		jQuery(this.div).draggable('enable');
	}
	else if (direction in MOVERESIZE_DIRECTION_JS_NAME) {
		var js_dir = MOVERESIZE_DIRECTION_JS_NAME[direction];
		var resize_widget = jQuery(this.div).find(".ui-resizable-handle.ui-resizable-"+js_dir).first();
		if (resize_widget) {
			var pageX = resize_widget.offset().left;
			var pageY = resize_widget.offset().top;
			resize_widget.trigger("mouseover");
			resize_widget.trigger({ type: "mousedown", which: 1, pageX: pageX, pageY: pageY });
		}
	}
}


/**
 * Returns the geometry of the window backing image,
 * the inner window geometry (without any borders or top bar).
 */
XpraWindow.prototype.get_internal_geometry = function() {
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
	if (this.debug) {
		console.debug("got mouse click at ", mx, my)
	}
	// mouse click event is from canvas just for this window so no need to check
	// internal geometry anymore
	this.mouse_click_cb(this, button, pressed, mx, my, modifiers, buttons);
};

/**
 * Handle mouse move from this window's canvas,
 * then we fire "mouse_move_cb" (if it is set).
 */
XpraWindow.prototype.handle_mouse_move = function(mx, my, modifiers, buttons) {
	this.mouse_move_cb(this, mx, my, modifiers, buttons);
};


XpraWindow.prototype.update_icon = function(width, height, encoding, img_data) {
	if (encoding=="png") {
		//move title to the right:
		$("#title"+ String(this.wid)).css('left', 32);
		jQuery('#windowicon' + String(this.wid)).attr('src', "data:image/"+encoding+";base64," + this._arrayBufferToBase64(img_data));
	}
};


XpraWindow.prototype.reset_cursor = function() {
	jQuery("#"+String(this.wid)).css("cursor", 'default');
};

XpraWindow.prototype.set_cursor = function(encoding, w, h, xhot, yhot, img_data) {
	if (encoding=="png") {
		var cursor_url = "url('data:image/"+encoding+";base64," + window.btoa(img_data) + "')";
		jQuery("#"+String(this.wid)).css("cursor", cursor_url+", default");
		//CSS3 with hotspot:
		jQuery("#"+String(this.wid)).css("cursor", cursor_url+" "+xhot+" "+yhot+", auto");
	}
};



/**
 * This function draws the contents of the off-screen canvas to the visible
 * canvas. However the drawing is requested by requestAnimationFrame which allows
 * the browser to group screen redraws together, and automatically adjusts the
 * framerate e.g if the browser window/tab is not visible.
 */
XpraWindow.prototype.draw = function() {
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
 * The following function inits the Broadway h264 decoder
 */
XpraWindow.prototype._init_broadway = function(enc_width, enc_height, width, height) {
	var me = this;
	this.broadway_decoder = new Decoder({
		"rgb": 	true,
		"size": { "width" : enc_width, "height" : enc_height },
	});
	this.log("broadway decoder initialized");
	this.broadway_paint_location = [0, 0];
	this.broadway_decoder.onPictureDecoded = function(buffer, p_width, p_height, infos) {
		if(this.debug) {
			console.debug("broadway picture decoded: ", buffer.length, "bytes, size ", p_width, "x", p_height+", paint location: ", me.broadway_paint_location,"with infos=", infos);
		}
		if(!me.broadway_decoder) {
			return;
		}
		var img = me.offscreen_canvas_ctx.createImageData(p_width, p_height);
		img.data.set(buffer);
		var x = me.broadway_paint_location[0];
		var y = me.broadway_paint_location[1];
		me.offscreen_canvas_ctx.putImageData(img, x, y);
		if(enc_width!=width || enc_height!=height) {
			//scale it:
			me.offscreen_canvas_ctx.drawImage(me.offscreen_canvas, x, y, p_width, p_height, x, y, width, height);
		}
	};
};

XpraWindow.prototype._close_broadway = function() {
	this.broadway_decoder = null;
}


XpraWindow.prototype._close_video = function() {
	if(this.debug) {
		console.debug("close_video: video_source_buffer="+this.video_source_buffer+", media_source="+this.media_source+", video="+this.video);
	}
	this.video_source_ready = false;
	if(this.video) {
		if(this.media_source) {
			try {
				if(this.video_source_buffer) {
					this.media_source.removeSourceBuffer(this.video_source_buffer);
				}
				this.media_source.endOfStream();
			} catch(e) {
				this.warn("video media source EOS error: "+e);
			}
			this.video_source_buffer = null;
			this.media_source = null;
		}
		this.video.remove();
		this.video = null;
	}
}

XpraWindow.prototype._push_video_buffers = function() {
	if(this.debug) {
		console.debug("_push_video_buffers()");
	}
	var vsb = this.video_source_buffer;
	var vb = this.video_buffers;
	if(!vb || !vsb || !this.video_source_ready) {
		return;
	}
	if(vb.length==0 && this.video_buffers_count==0) {
		return;
	}
	while(vb.length>0 && !vsb.updating) {
		var buffers = vb.splice(0, 20);
		var buffer = [].concat.apply([], buffers);
		vsb.appendBuffer(new Uint8Array(buffer).buffer);
		/*
		 * one at a time:
		var img_data = vb.shift();
        var array = new Uint8Array(img_data);
	    vsb.appendBuffer(array.buffer);
		 */
	    this.video_buffers_count += buffers.length;
	}
	if(vb.length>0) {
		setTimeout(this._push_video_buffers, 25);
	}
}

XpraWindow.prototype._init_video = function(width, height, coding, profile, level) {
	var me = this;
	this.media_source = MediaSourceUtil.MediaSource();
	if(this.debug) {
		MediaSourceUtil.addMediaSourceEventDebugListeners(this.media_source, "video");
	}
	//<video> element:
	this.video = document.createElement("video");
	this.video.setAttribute('autoplay', true);
	this.video.setAttribute('muted', true);
	this.video.setAttribute('width', width);
	this.video.setAttribute('height', height);
	this.video.style.pointerEvents = "all";
	this.video.style.position = "absolute";
	this.video.style.zIndex = this.div.css("z-index")+1;
	this.video.style.left  = ""+this.leftoffset+"px";
	this.video.style.top = ""+this.topoffset+"px";
	if(this.debug) {
		MediaSourceUtil.addMediaElementEventDebugListeners(this.video, "video");
		this.video.setAttribute('controls', "controls");
	}
	this.video.addEventListener('error', function() { me.error("video error"); });
	this.video.src = window.URL.createObjectURL(this.media_source);
	//this.video.src = "https://html5-demos.appspot.com/static/test.webm"
	this.video_buffers = []
	this.video_buffers_count = 0;
	this.video_source_ready = false;

	var codec_string = "";
	if(coding=="h264+mp4" || coding=="mpeg4+mp4") {
		//ie: 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'
		codec_string = 'video/mp4; codecs="avc1.' + MediaSourceConstants.H264_PROFILE_CODE[profile] + MediaSourceConstants.H264_LEVEL_CODE[level]+'"';
	}
	else if(coding=="vp8+webm") {
		codec_string = 'video/webm;codecs="vp8"';
	}
	else if(coding=="vp9+webm") {
		codec_string = 'video/webm;codecs="vp9"';
	}
	else {
		throw Exception("invalid encoding: "+coding);
	}
	this.log("video codec string: "+codec_string+" for "+coding+" profile '"+profile+"', level '"+level+"'");
	this.media_source.addEventListener('sourceopen', function() {
		me.log("video media source open");
		var vsb = me.media_source.addSourceBuffer(codec_string);
	    vsb.mode = "sequence";
		me.video_source_buffer = vsb;
		if(this.debug) {
			MediaSourceUtil.addSourceBufferEventDebugListeners(vsb, "video");
		}
		vsb.addEventListener('error', function(e) { me.error("video source buffer error"); });
		vsb.addEventListener('waiting', function() {
			me._push_video_buffers();
		});
		//push any buffers that may have accumulated since we initialized the video element:
		me._push_video_buffers();
		me.video_source_ready = true;
	});
	this.canvas.parentElement.appendChild(this.video);
};

XpraWindow.prototype._non_video_paint = function(coding) {
	if(this.video && this.video.style.zIndex!="-1") {
		if(this.debug) {
			console.debug("bringing canvas above video for "+coding+" paint event");
		}
		//push video under the canvas:
		this.video.style.zIndex = "-1";
		//copy video to canvas:
		var width = this.video.getAttribute("width");
		var height = this.video.getAttribute("height");
        this.offscreen_canvas_ctx.drawImage(this.video, 0, 0, width, height);
	}
}


/**
 * Updates the window image with new pixel data
 * we have received from the server.
 * The image is painted into off-screen canvas.
 */
XpraWindow.prototype.paint = function paint() {
	//process all paint request in order using the paint_queue:
	var item = Array.prototype.slice.call(arguments);
	this.paint_queue.push(item);
	this.may_paint_now();
}

/**
 * Pick items from the paint_queue
 * if we're not already in the process of painting something.
 */
XpraWindow.prototype.may_paint_now = function paint() {
 	if (this.debug) {
		console.debug("may_paint_now() paint pending=", this.paint_pending, ", paint queue length=", this.paint_queue.length);
	}
	while (!this.paint_pending && this.paint_queue.length>0) {
		this.paint_pending = true;
		var item = this.paint_queue.shift();
		this.do_paint.apply(this, item);
	}
}

var DEFAULT_BOX_COLORS = {
        "png"     : "yellow",
        "h264"    : "blue",
        "vp8"     : "green",
        "rgb24"   : "orange",
        "rgb32"   : "red",
        "jpeg"    : "purple",
        "png/P"   : "indigo",
        "png/L"   : "teal",
        "h265"    : "khaki",
        "vp9"     : "lavender",
        "mpeg4"   : "black",
        "scroll"  : "brown",
        }

XpraWindow.prototype.do_paint = function paint(x, y, width, height, coding, img_data, packet_sequence, rowstride, options, decode_callback) {
 	if (this.debug) {
 		console.debug("do_paint("+img_data.length+" bytes of "+("zlib" in options?"zlib ":"")+coding+" data "+width+"x"+height+" at "+x+","+y+") focused="+this.focused);
 	}
	var me = this;

	if(this.offscreen_canvas_mode!='2d') {
		this._init_2d_canvas();
	}
	var enc_width = width;
	var enc_height = height;
	var scaled_size = options["scaled_size"];
	if(scaled_size) {
		enc_width = scaled_size[0];
		enc_height = scaled_size[1];
	}
	function paint_box(color, px, py, pw, ph) {
		me.offscreen_canvas_ctx.strokeStyle = color;
		me.offscreen_canvas_ctx.lineWidth = "2";
		me.offscreen_canvas_ctx.strokeRect(px, py, pw, ph);
	}

	function painted(skip_box) {
		me.paint_pending = false;
		decode_callback(me.client);
		if (me.debug && !skip_box) {
			var color = DEFAULT_BOX_COLORS[coding] || "white";
			paint_box(color, x, y, width, height);
		}
		me.may_paint_now();
	}

	if (coding=="rgb32") {
		this._non_video_paint(coding);
		var img = this.offscreen_canvas_ctx.createImageData(width, height);
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
			this.error("data size mismatch: wanted",img.data.length,", got",img_data.length, ", stride",rowstride);
		} else {
			if (this.debug) {
				console.debug("got ",img_data.length,"to paint with stride",rowstride);
			}
		}
		img.data.set(img_data);
		this.offscreen_canvas_ctx.putImageData(img, x, y);
		painted();
	}
	else if (coding=="jpeg" || coding=="png") {
		this._non_video_paint(coding);
		var img = this.offscreen_canvas_ctx.createImageData(width, height);
		var j = new Image();
		j.onload = function () {
			me.offscreen_canvas_ctx.drawImage(j, x, y);
			painted();
		};
		j.src = "data:image/"+coding+";base64," + this._arrayBufferToBase64(img_data);
	}
	else if (coding=="h264") {
		var frame = options["frame"] || -1;
		if(frame==0) {
			this._close_broadway();
		}
		if(!this.broadway_decoder) {
			this._init_broadway(enc_width, enc_height, width, height);
		}
		this.broadway_paint_location = [x, y];
		// we can pass a buffer full of NALs to decode() directly
		// as long as they are framed properly with the NAL header
		this.broadway_decoder.decode(new Uint8Array(img_data));
		// broadway decoding is synchronous:
		// (and already painted via the onPictureDecoded callback)
		painted();
	}
	else if (coding=="h264+mp4" || coding=="vp8+webm" || coding=="mpeg4+mp4") {
		var frame = options["frame"] || -1;
		if(frame==0) {
			this._close_video();
		}
		if(!this.video) {
			var profile = options["profile"] || "baseline";
			var level  = options["level"] || "3.0";
			this._init_video(width, height, coding, profile, level);
		}
		else {
			//keep it above the div:
			this.video.style.zIndex = this.div.css("z-index")+1;
		}
		if(img_data.length>0) {
			if(this.debug) {
				console.debug("video state="+MediaSourceConstants.READY_STATE[this.video.readyState]+", network state="+MediaSourceConstants.NETWORK_STATE[this.video.networkState]);
				console.debug("video paused="+this.video.paused+", video buffers="+this.video_buffers.length);
			}
			this.video_buffers.push(img_data);
			if(this.video.paused) {
				this.video.play();
			}
			this._push_video_buffers();
			//try to throttle input:
			var delay = Math.max(10, 50*(this.video_buffers.length-25));
			var me = this;
			setTimeout(function() {
				painted();
			}, delay);
			//console.debug("video queue: ", this.video_buffers.length);
		}
	}
	else if (coding=="scroll") {
		this._non_video_paint(coding);
		for(var i=0,j=img_data.length;i<j;++i) {
			var scroll_data = img_data[i];
			var sx = scroll_data[0],
				sy = scroll_data[1],
				sw = scroll_data[2],
				sh = scroll_data[3],
				xdelta = scroll_data[4],
				ydelta = scroll_data[5];
			this.offscreen_canvas_ctx.drawImage(this.offscreen_canvas, sx, sy, sw, sh, sx+xdelta, sy+ydelta, sw, sh);
			if (this.debug) {
				paint_box("brown", sx+xdelta, sy+ydelta, sw, sh);
			}
		}
		painted(true);
	}
	else {
		throw "unsupported coding " + coding;
	}
};

/**
 * Close the window and free all resources
 */
XpraWindow.prototype.destroy = function destroy() {
	// remove div
	this._close_broadway();
	this._close_video();
	this.div.remove();
};
