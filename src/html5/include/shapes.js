// By Simon Sarris
// www.simonsarris.com
// sarris@acm.org
//
// Code from the following pages merged by Andrew Clark (amclark7@gmail.com):
//	 http://simonsarris.com/blog/510-making-html5-canvas-useful
//	 http://simonsarris.com/blog/225-canvas-selecting-resizing-shape
// Last update June 2013
//
// Free to use and distribute at will
// So long as you are nice to people, etc

// Constructor for Shape objects to hold data for all drawn objects.
// For now they will just be defined as rectangles.
function Shape(state, x, y, w, h, fill) {
	"use strict";
	// This is a very simple and unsafe constructor. All we're doing is checking if the values exist.
	// "x || 0" just means "if there is a value for x, use that. Otherwise use 0."
	// But we aren't checking anything else! We could put "Lalala" for the value of x
	this.state = state;
	this.x = x || 0;
	this.y = y || 0;
	this.w = w || 1;
	this.h = h || 1;
	this.fill = fill || '#AAAAAA';
	this.geometry_cb = null;
};

// Draws this shape to a given context
Shape.prototype.draw = function(ctx, optionalColor) {
	"use strict";
	ctx.fillStyle = this.fill;
	ctx.fillRect(this.x, this.y, this.w, this.h);
	if (this.state.selection === this) {
		//window.alert("Shape.prototype.draw_selection="+Shape.prototype.draw_selection);
		this.draw_selection(ctx, optionalColor);
	}
};

Shape.prototype.draw_selection = function(ctx, optionalColor) {
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

// Determine if a point is inside the shape's bounds
function rectangle_contains(rect, mx, my) {
	"use strict";
	// All we have to do is make sure the Mouse X,Y fall in the area between
	// the shape's X and (X + Height) and its Y and (Y + Height)
	return	(rect.x <= mx) && (rect.x + rect.w >= mx) &&
					(rect.y <= my) && (rect.y + rect.h >= my);
};
Shape.prototype.contains = function(mx, my) {
	"use strict";
	return rectangle_contains(this.get_window_geometry(), mx, my);
};

// The whole shape is the grab area:
Shape.prototype.is_grab_area = Shape.prototype.contains;


//The geometry of this shape:
Shape.prototype.get_window_geometry = function() {
	"use strict";
	return { x : this.x, y : this.y, w : this.w, h : this.h };
};


Shape.prototype.move_resize = function(x, y, w, h) {
	"use strict";
	// when resizing, a negative width or height is possible
	// in that case, swap position:
	if (w < 0) {
		w = -w;
		x -= w;
	}
	if (h < 0) {
		h = -h;
		y -= h;
	}
	// try to honour position, but make sure we don't put the window decorations at negative coords:
	this.x = Math.max((x || 0), 0);
	this.y = Math.max((y || 0), 0);
	this.w = Math.max((w || this.w), 1);
	this.h = Math.max((h || this.h), 1);
	if (this.geometry_cb!=null) {
		this.geometry_cb(this);
	}
	//show("move_resize("+x+", "+y+", "+w+", "+h+") new geometry="+this.get_window_geometry().toSource());
};

Shape.prototype.move = function(x, y) {
	"use strict";
	this.move_resize(x, y, this.w, this.h);
};

Shape.prototype.resize = function(w, h) {
	"use strict";
	// when resizing, a negative width or height is possible
	// in that case, swap position:
	this.move_resize(this.x, this.y, w, h);
};

Shape.prototype.handle_mouse_click = function(button, pressed, mx, my, modifiers, buttons) {
	// nothing here
};
Shape.prototype.handle_mouse_move = function(mx, my, modifiers, buttons) {
	// nothing here
};


function CanvasState(canvas) {
	"use strict";
	// **** First some setup! ****

	this.canvas = canvas;
	this.width = canvas.width;
	this.height = canvas.height;
	this.ctx = canvas.getContext('2d');
	// This complicates things a little but but fixes mouse co-ordinate problems
	// when there's a border or padding. See getMouse for more detail
	var stylePaddingLeft, stylePaddingTop, styleBorderLeft, styleBorderTop,
			html, self, i;
	if (document.defaultView && document.defaultView.getComputedStyle) {
		this.stylePaddingLeft	= parseInt(document.defaultView.getComputedStyle(canvas, null).paddingLeft, 10)		|| 0;
		this.stylePaddingTop	= parseInt(document.defaultView.getComputedStyle(canvas, null).paddingTop, 10)		|| 0;
		this.styleBorderLeft	= parseInt(document.defaultView.getComputedStyle(canvas, null).borderLeftWidth, 10)	|| 0;
		this.styleBorderTop		= parseInt(document.defaultView.getComputedStyle(canvas, null).borderTopWidth, 10)	|| 0;
	}
	// Some pages have fixed-position bars (like the stumbleupon bar) at the top or left of the page
	// They will mess up mouse coordinates and this fixes that
	html = document.body.parentNode;
	this.htmlTop = html.offsetTop;
	this.htmlLeft = html.offsetLeft;

	// **** Keep track of state! ****

	this.valid = false;			// when set to false, the canvas will redraw everything
	this.shapes = {};			// the collection of things to be drawn, the key is the stacking order (highest first)
	this.stacking = 0;
	this.dragging = false;		// Keep track of when we are dragging
	this.resizeDragging = false;// Keep track of resize
	this.expectResize = -1;		// save the # of the selection handle
	// the current selected object. In the future we could turn this into an array for multiple selection
	this.selection = null;
	this.dragoffx = 0;			// See mousedown and mousemove events for explanation
	this.dragoffy = 0;

	// New, holds the 8 tiny boxes that will be our selection handles
	// the selection handles will be in this order:
	// 0  1  2
	// 3     4
	// 5  6  7
	this.selectionHandles = [];
	for (i = 0; i < 8; i += 1) {
		this.selectionHandles.push(new Shape(this));
	}

	// Hook up the events we want to receive:
	this.event_listeners = []
	var listeners = [
			['selectstart'	, false],
			['mousedown'	, true],
			['mousemove'	, true],
			['mouseup'		, true],
			['dblclick'		, true],
			];
	for (i = 0; i < listeners.length; i += 1) {
		var l = listeners[i];
		this.registerEventListener(l[0], l[1]);
	}

	// disable right click menu:
	window.oncontextmenu = function(e) {
		//showCustomMenu();
		return false;
	}

	// **** Options! ****
	this.selectionColor = '#CC0000';
	this.selectionWidth = 2;
	this.selectionBoxSize = 6;
	this.selectionBoxColor = 'darkred';
	this.interval = 30;

	// This is an example of a closure:
	var self = this;
	this.repaint_timer = setInterval(function() { self.draw(); }, self.interval);
};


// Finds the shape at the top of the stack:
CanvasState.prototype.topOfStack = function() {
	if (this.shapes.length==0)
		return null;
	var keys = Object.keys(this.shapes).sort().reverse();
	//show("topOfStack: "+keys.toSource()+" [0]="+keys[0]);
	return this.shapes[keys[0]];
}

// Look for the shape starting at the top of the stack
CanvasState.prototype.findShape = function(mx, my) {
	var mySel;
	var stacking;
	var keys = Object.keys(this.shapes).sort().reverse();
	var l = keys.length;
	for (i = 0; i < l; i += 1) {
		stacking = keys[i];
		mySel = this.shapes[stacking];
		if (mySel.contains(mx, my))
			return mySel;
	}
	return null;
}

CanvasState.prototype.addShape = function(shape) {
	"use strict";
	this.stacking += 1;
	this.shapes[this.stacking] = shape;
	this.valid = false;
};

CanvasState.prototype.removeShape = function(shape) {
	"use strict";
	var stacking;
	var keys = Object.keys(this.shapes);
	var l = keys.length;
	for (i = l-1; i >= 0; i -= 1) {
		stacking = keys[i];
		if (shape==this.shapes[stacking]) {
			delete this.shapes[stacking];
			this.valid = false;
			break;
		}
	}
};

CanvasState.prototype.raiseShape = function(shape) {
	"use strict";
	var stacking;
	var keys = Object.keys(this.shapes);
	var l = keys.length;
	for (i = l-1; i >= 0; i -= 1) {
		stacking = keys[i];
		if (shape==this.shapes[stacking]) {
			if (stacking==this.stacking)
				return;
			delete this.shapes[stacking];
			this.stacking += 1;
			this.shapes[this.stacking] = shape;
			this.valid = false;
			//show("raiseShape re stacked "+shape+" from "+stacking+" to "+this.stacking);
			break;
		}
	}
};

CanvasState.prototype.on_dblclick = function(e) {
	//TODO!
}

CanvasState.prototype.on_mousemove = function(e) {
	var mouse = this.getMouse(e),
			mx = mouse.x,
			my = mouse.y,
			handled = false,
			i, cur;
	//show("mousemove mouse="+mouse.toSource()+", dragging="+this.dragging);
	if (this.dragging){
		// We don't want to drag the object by its top-left corner, we want to drag it
		// from where we clicked. Thats why we saved the offset and use it here
		this.selection.move(mouse.x - this.dragoffx, mouse.y - this.dragoffy);
		this.valid = false; // Something's dragging so we must redraw
		handled = true;
	} else if (this.resizeDragging) {
		// time ro resize!
		var shape = this.selection;
		var geom = shape.get_window_geometry();

		// 0  1  2
		// 3     4
		// 5  6  7
		switch (this.expectResize) {
			case 0:
				shape.move_resize(mx, my, geom.w + geom.x - mx, geom.h + geom.y - my);
				break;
			case 1:
				shape.move_resize(geom.x, my, geom.w, geom.h + geom.y - my);
				break;
			case 2:
				shape.move_resize(geom.x, my, geom.w + mx - geom.x, geom.h + geom.y - my);
				break;
			case 3:
				shape.move_resize(mx, geom.y, geom.w + geom.x - mx, geom.h);
				break;
			case 4:
				shape.move_resize(geom.x, geom.y, mx - geom.x, geom.h);
				break;
			case 5:
				shape.move_resize(mx, geom.y, geom.w + geom.x - mx, my - geom.y);
				break;
			case 6:
				shape.move_resize(geom.x, geom.y, geom.w, my - geom.y);
				break;
			case 7:
				shape.move_resize(geom.x, geom.y, mx - geom.x, my - geom.y);
				break;
		}
		this.valid = false; // Something's dragging so we must redraw
		handled = true;
	}

	// if there's a selection see if we grabbed one of the selection handles
	if (this.selection !== null && !this.resizeDragging) {
		for (i = 0; i < 8; i += 1) {
			// 0  1  2
			// 3     4
			// 5  6  7

			cur = this.selectionHandles[i];

			// we dont need to use the ghost context because
			// selection handles will always be rectangles
			if (mx >= cur.x && mx <= cur.x + this.selectionBoxSize &&
					my >= cur.y && my <= cur.y + this.selectionBoxSize) {
				// we found one!
				this.expectResize = i;
				this.valid = false;
				handled = true;

				var sc = {
						0 : 'nw-resize',
						1 : 'n-resize',
						2 : 'ne-resize',
						3 : 'w-resize',
						4 : 'e-resize',
						5 : 'sw-resize',
						6 : 's-resize',
						7 : 'se-resize'
				}[i];
				if (sc!=undefined)
					this.canvas.style.cursor = sc;
				break;
			}
		}
		if (!handled) {
			// not over a selection box, return to normal
			this.resizeDragging = false;
			this.expectResize = -1;
			this.canvas.style.cursor = 'auto';
		}
	}

	// pass move to the area:
	if (!handled) {
		var mySel = this.findShape(mx, my);
		if (mySel!=null) {
			var modifiers = [];
			var buttons = [];
			mySel.handle_mouse_move(mx, my, modifiers, buttons);
		}
	}
};

CanvasState.prototype.on_mousedown = function(e) {
	var mouse, mx, my, shapes, l, i, mySel;
	if (this.expectResize !== -1) {
		this.resizeDragging = true;
		return;
	}
	mouse = this.getMouse(e);
	mx = mouse.x;
	my = mouse.y;

	mySel = this.findShape(mx, my);
	if (mySel==null) {
		// havent returned means we have failed to select anything.
		// If there was an object selected, we deselect it
		if (this.selection) {
			this.selection = null;
			this.valid = false; // Need to clear the old selection border
		}
		return;
	}
	this.raiseShape(mySel);

	if (mySel.is_grab_area(mx, my)) {
		// only left click does anything here:
		if (mouse.button==1) {
			// Keep track of where in the object we clicked
			// so we can move it smoothly (see mousemove)
			this.dragoffx = mx - mySel.x;
			this.dragoffy = my - mySel.y;
			this.dragging = true;
			this.selection = mySel;
			this.valid = false;
		}
		return;
	}
	// pass the click to the area:
	var modifiers = [];
	var buttons = [];
	mySel.handle_mouse_click(mouse.button, true, mx, my, modifiers, buttons);
	return;
};

CanvasState.prototype.on_mouseup = function(e) {
	// if not handling it ourselves, pass it down:
	var mouse = this.getMouse(e),
			mx = mouse.x,
			my = mouse.y;
	if (!this.dragging && !this.resizeDragging) {
		var mySel = this.findShape(mx, my);
		if (mySel!=null) {
			var modifiers = [];
			var buttons = [];
			mySel.handle_mouse_click(mouse.button, false, mx, my, modifiers, buttons);
		}
	}

	this.dragging = false;
	this.resizeDragging = false;
	this.expectResize = -1;
	if (this.selection !== null) {
		this.canvas.style.cursor = 'auto';
		this.selection = null;
		this.valid = false;
	}
};

CanvasState.prototype.on_selectstart = function(e) {
	e.preventDefault();
	return false;
};


CanvasState.prototype.registerEventListener = function(event_type, useCapture) {
	var self = this;
	var fn_name = "on_"+event_type;
	var handler = self[fn_name];
	var fn = function(e) {
		handler.call(self, e);
	};
	this.event_listeners[event_type] = fn;
	this.canvas["on"+event_type] = fn;
};


CanvasState.prototype.destroy = function() {
	"use strict";
	if (this.canvas==null)
		return;
	var event_types = Object.keys(this.event_listeners);
	for (var i = 0; i < event_types.length; i += 1) {
		var event_type = event_types[i];
		this.canvas["on"+event_type] = null;
	}
	clearInterval(this.repaint_timer);
	this.canvas = null;
	this.valid = true;
	this.shapes = {};
	this.stacking = 0;
	this.dragging = false;
	this.resizeDragging = false;
	this.expectResize = -1;
	this.selection = null;
	this.dragoffx = 0;
	this.dragoffy = 0;
	this.ctx.clearRect(0, 0, this.width, this.height);
	this.width = 0;
	this.height = 0;
	this.ctx = null;
};

CanvasState.prototype.clear = function() {
	"use strict";
	this.ctx.clearRect(0, 0, this.width, this.height);
};

CanvasState.prototype.invalidate = function() {
	this.valid = false;
};

// While draw is called as often as the INTERVAL variable demands,
// It only ever does something if the canvas gets invalidated by our code
CanvasState.prototype.draw = function() {
	"use strict";
	var ctx, shapes, l, i, shape, mySel;
	// if our state is invalid, redraw and validate!
	if (!this.valid) {
		ctx = this.ctx;
		shapes = this.shapes;
		this.clear();

		// ** Add stuff you want drawn in the background all the time here **

		// draw all shapes in ascending stacking order:
		var stacking;
		var keys = Object.keys(this.shapes).sort();
		var l = keys.length;
		for (i = 0; i < l; i += 1) {
			stacking = keys[i];
			shape = shapes[stacking];
			// We can skip the drawing of elements that have moved off the screen:
			if (shape.x <= this.width && shape.y <= this.height &&
					shape.x + shape.w >= 0 && shape.y + shape.h >= 0) {
				shape.draw(ctx);
			}
		}

		// draw selection
		// right now this is just a stroke along the edge of the selected Shape
		if (this.selection !== null) {
			ctx.strokeStyle = this.selectionColor;
			ctx.lineWidth = this.selectionWidth;
			mySel = this.selection;
			ctx.strokeRect(mySel.x,mySel.y,mySel.w,mySel.h);
		}

		// ** Add stuff you want drawn on top all the time here **

		this.valid = true;
	}
};


// Creates an object with x and y defined, set to the mouse position relative to the state's canvas
// If you wanna be super-correct this can be tricky, we have to worry about padding and borders
CanvasState.prototype.getMouse = function(e) {
	"use strict";
	var element = this.canvas, offsetX = 0, offsetY = 0, mx, my;

	// Compute the total offset
	if (element.offsetParent !== undefined) {
		do {
			offsetX += element.offsetLeft;
			offsetY += element.offsetTop;
			element = element.offsetParent;
		} while (element);
	}

	// Add padding and border style widths to offset
	// Also add the <html> offsets in case there's a position:fixed bar
	offsetX += this.stylePaddingLeft + this.styleBorderLeft + this.htmlLeft;
	offsetY += this.stylePaddingTop + this.styleBorderTop + this.htmlTop;

	mx = e.pageX - offsetX;
	my = e.pageY - offsetY;

	var mbutton = 0;
	if ("which" in e)  // Gecko (Firefox), WebKit (Safari/Chrome) & Opera
		mbutton = Math.max(0, e.which);
	else if ("button" in e)  // IE, Opera (zero based)
		mbutton = Math.max(0, e.button)+1;
	//show("getmouse: button="+mbutton+", which="+e.which+", button="+e.button);

	// We return a simple javascript object (a hash) with x and y defined
	return {x: mx, y: my, button: mbutton};
};

// If you dont want to use <body onLoad='init()'>
// You could uncomment this init() reference and place the script reference inside the body tag
//init();
