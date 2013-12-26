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
}

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
Shape.prototype.contains = function(mx, my) {
	"use strict";
	// All we have to do is make sure the Mouse X,Y fall in the area between
	// the shape's X and (X + Height) and its Y and (Y + Height)
	return	(this.x <= mx) && (this.x + this.w >= mx) &&
					(this.y <= my) && (this.y + this.h >= my);
};

// The whole shape is the grab area:
Shape.prototype.is_grab_area = Shape.prototype.contains;


//The geometry of this shape:
Shape.prototype.get_window_geometry = function(ctx) {
	"use strict";
	return { x : this.x, y : this.y, w : this.w, h : this.h };
}


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
}

Shape.prototype.move = function(x, y) {
	"use strict";
	this.move_resize(x, y, this.w, this.h);
}

Shape.prototype.resize = function(w, h) {
	"use strict";
	// when resizing, a negative width or height is possible
	// in that case, swap position:
	this.move_resize(this.x, this.y, w, h);
}




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
			html, myState, i;
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
	this.shapes = [];			// the collection of things to be drawn
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

	// **** Then events! ****

	// This is an example of a closure!
	// Right here "this" means the CanvasState. But we are making events on the Canvas itself,
	// and when the events are fired on the canvas the variable "this" is going to mean the canvas!
	// Since we still want to use this particular CanvasState in the events we have to save a reference to it.
	// This is our reference!
	myState = this;

	//fixes a problem where double clicking causes text to get selected on the canvas
	canvas.addEventListener('selectstart', function(e) { e.preventDefault(); return false; }, false);
	// Up, down, and move are for dragging
	canvas.addEventListener('mousedown', function(e) {
		var mouse, mx, my, shapes, l, i, mySel;
		if (myState.expectResize !== -1) {
			myState.resizeDragging = true;
			return;
		}
		mouse = myState.getMouse(e);
		if (mouse.button!=0)
			return;
		show("mouse="+mouse.toSource());
		mx = mouse.x;
		my = mouse.y;

		shapes = myState.shapes;
		l = shapes.length;
		for (i = l-1; i >= 0; i -= 1) {
			if (shapes[i].is_grab_area(mx, my)) {
				mySel = shapes[i];
				// Keep track of where in the object we clicked
				// so we can move it smoothly (see mousemove)
				myState.dragoffx = mx - mySel.x;
				myState.dragoffy = my - mySel.y;
				myState.dragging = true;
				myState.selection = mySel;
				myState.valid = false;
				return;
			}
		}
		// havent returned means we have failed to select anything.
		// If there was an object selected, we deselect it
		if (myState.selection) {
			myState.selection = null;
			myState.valid = false; // Need to clear the old selection border
		}
	}, true);
	canvas.addEventListener('mousemove', function(e) {
		var mouse = myState.getMouse(e),
				mx = mouse.x,
				my = mouse.y,
				oldx, oldy, i, cur;
		if (myState.dragging){
			mouse = myState.getMouse(e);
			// We don't want to drag the object by its top-left corner, we want to drag it
			// from where we clicked. Thats why we saved the offset and use it here
			myState.selection.move(mouse.x - myState.dragoffx, mouse.y - myState.dragoffy);
			myState.valid = false; // Something's dragging so we must redraw
		} else if (myState.resizeDragging) {
			// time ro resize!
			var shape = myState.selection;
			var geom = shape.get_window_geometry();

			// 0  1  2
			// 3     4
			// 5  6  7
			switch (myState.expectResize) {
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
			myState.valid = false; // Something's dragging so we must redraw
		}

		// if there's a selection see if we grabbed one of the selection handles
		if (myState.selection !== null && !myState.resizeDragging) {
			for (i = 0; i < 8; i += 1) {
				// 0  1  2
				// 3     4
				// 5  6  7

				cur = myState.selectionHandles[i];

				// we dont need to use the ghost context because
				// selection handles will always be rectangles
				if (mx >= cur.x && mx <= cur.x + myState.selectionBoxSize &&
						my >= cur.y && my <= cur.y + myState.selectionBoxSize) {
					// we found one!
					myState.expectResize = i;
					myState.valid = false;

					switch (i) {
						case 0:
							this.style.cursor='nw-resize';
							break;
						case 1:
							this.style.cursor='n-resize';
							break;
						case 2:
							this.style.cursor='ne-resize';
							break;
						case 3:
							this.style.cursor='w-resize';
							break;
						case 4:
							this.style.cursor='e-resize';
							break;
						case 5:
							this.style.cursor='sw-resize';
							break;
						case 6:
							this.style.cursor='s-resize';
							break;
						case 7:
							this.style.cursor='se-resize';
							break;
					}
					return;
				}

			}
			// not over a selection box, return to normal
			myState.resizeDragging = false;
			myState.expectResize = -1;
			this.style.cursor = 'auto';
		}
	}, true);
	canvas.addEventListener('mouseup', function(e) {
		myState.dragging = false;
		myState.resizeDragging = false;
		myState.expectResize = -1;
		if (myState.selection !== null) {
			this.style.cursor = 'auto';
			myState.selection = null;
			myState.valid = false;
		}
	}, true);

	// disable right click menu:
	window.oncontextmenu = function(e) {
	    //showCustomMenu();
	    return false;
	}

	// double click
	canvas.addEventListener('dblclick', function(e) {
		//TODO!
	}, true);

	// **** Options! ****
	this.selectionColor = '#CC0000';
	this.selectionWidth = 2;
	this.selectionBoxSize = 6;
	this.selectionBoxColor = 'darkred';
	this.interval = 30;
	setInterval(function() { myState.draw(); }, myState.interval);
}

CanvasState.prototype.addShape = function(shape) {
	"use strict";
	this.shapes.push(shape);
	this.valid = false;
};

CanvasState.prototype.removeShape = function(shape) {
	"use strict";
	var index = this.shapes.indexOf(shape);
	if (index > -1) {
		this.shapes.splice(index, 1);
		this.valid = false;
	}
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

		// draw all shapes
		l = shapes.length;
		for (i = 0; i < l; i += 1) {
			shape = shapes[i];
			// We can skip the drawing of elements that have moved off the screen:
			if (shape.x <= this.width && shape.y <= this.height &&
					shape.x + shape.w >= 0 && shape.y + shape.h >= 0) {
				shapes[i].draw(ctx);
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
        mbutton = Math.max(0, e.which-2);
    else if ("button" in e)  // IE, Opera
        mbutton = Math.max(0, e.button - 1);

	// We return a simple javascript object (a hash) with x and y defined
	return {x: mx, y: my, button: mbutton};
};

// If you dont want to use <body onLoad='init()'>
// You could uncomment this init() reference and place the script reference inside the body tag
//init();

