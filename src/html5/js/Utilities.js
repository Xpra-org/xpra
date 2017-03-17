/*
 * This file is part of Xpra.
 * Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2016 Spikes, Inc.
 * Licensed under MPL 2.1, see:
 * http://www.mozilla.org/MPL/2.1/
 *
 */

'use strict';

var Utilities = {
	VERSION	: "2.1",

	error : function() {
		console.error.apply(console, arguments);
	},
	warn : function() {
		console.log.apply(console, arguments);
	},
	log : function() {
		console.log.apply(console, arguments);
	},

	getHexUUID: function() {
		var s = [];
		var hexDigits = "0123456789abcdef";
		for (var i = 0; i < 36; i++) {
			if (i==8 || i==13 || i==18 || i==23) {
				s[i] = "-";
			}
			else {
				s[i] = hexDigits.substr(Math.floor(Math.random() * 0x10), 1);
			}
		}
		var uuid = s.join("");
		return uuid;
	},

	getSalt: function(l) {
		if(l<32 || l>256) {
			throw 'invalid salt length';
		}
		var s = '';
		while (s.length<l) {
			s += Utilities.getHexUUID();
		}
		return s.slice(0, l);
	},

	xorString: function(str1, str2){
		var result = '';
		if(str1.length !== str2.length) {
			throw 'strings must be equal length';
		}
		for(var i = 0; i < str1.length; i++) {
			result += String.fromCharCode(str1[i].charCodeAt(0) ^ str2[i].charCodeAt(0));
		}
		return result;
	},

	getPlatformProcessor: function() {
		//mozilla property:
		if (navigator.oscpu){
			return navigator.oscpu;
		}
		//ie:
		if (navigator.cpuClass) {
			return navigator.cpuClass;
		}
		return 'unknown';
	},

	getPlatformName: function() {
		if (navigator.appVersion.indexOf('Win') !== -1){
			return 'Microsoft Windows';
		}
		if (navigator.appVersion.indexOf('Mac') !== -1){
			return 'Mac OSX';
		}
		if (navigator.appVersion.indexOf('Linux') !== -1){
			return 'Linux';
		}
		if (navigator.appVersion.indexOf('X11') !== -1){
			return 'Posix';
		}
		return 'unknown';
	},

	getPlatform: function() {
		//use python style strings for platforms:
		if (navigator.appVersion.indexOf('Win') !== -1){
			return 'win32';
		}
		if (navigator.appVersion.indexOf('Mac') !== -1){
			return 'darwin';
		}
		if (navigator.appVersion.indexOf('Linux') !== -1){
			return 'linux2';
		}
		if (navigator.appVersion.indexOf('X11') !== -1){
			return 'posix';
		}
		return 'unknown';
	},

	getKeyboardLayout: function() {
		//IE:
		//navigator.systemLanguage
		//navigator.browserLanguage
		var v = window.navigator.userLanguage || window.navigator.language;
		//ie: v="en_GB";
		v = v.split(',')[0];
		var l = v.split('-', 2);
		if (l.length === 1){
			l = v.split('_', 2);
		}
		if (l.length === 1){
			return '';
		}
		//ie: "gb"
		return l[1].toLowerCase();
	},

	getAudioContextClass : function() {
		return window.AudioContext || window.webkitAudioContext || window.audioContext;
	},

	getAudioContext : function() {
		var acc = Utilities.getAudioContextClass();
		if(!acc) {
			return null;
		}
		return new acc();
	},

	isFirefox : function() {
		var ua = navigator.userAgent.toLowerCase();
		return ua.indexOf("firefox") >= 0;
	},
	isOpera : function() {
		var ua = navigator.userAgent.toLowerCase();
		return ua.indexOf("opera") >= 0;
	},
	isSafari : function() {
		var ua = navigator.userAgent.toLowerCase();
		return ua.indexOf("safari") >= 0 && ua.indexOf('chrome') < 0;
	},
	isChrome : function() {
		var ua = navigator.userAgent.toLowerCase();
		return ua.indexOf('chrome') >= 0 && ua.indexOf("safari") < 0;
	},
	isIE : function() {
		return navigator.userAgent.indexOf("MSIE") != -1;
	},

	getColorGamut : function() {
		if (!window.matchMedia) {
			//unknown
			return "";
		}
		else if (window.matchMedia('(color-gamut: rec2020)').matches) {
			return "rec2020";
		}
		else if (window.matchMedia('(color-gamut: p3)').matches) {
			return "P3";
		}
		else if (window.matchMedia('(color-gamut: srgb)').matches) {
			return "srgb";
		}
		else {
			return "";
		}
	},

	isEventSupported : function(event) {
		var testEl = document.createElement('div');
		var isSupported;

		event = 'on' + event;
		isSupported = (event in testEl);

		if (!isSupported) {
			testEl.setAttribute(event, 'return;');
			isSupported = typeof testEl[event] === 'function';
		}
		testEl = null;
		return isSupported;
	},

	//https://github.com/facebook/fixed-data-table/blob/master/src/vendor_upstream/dom/normalizeWheel.js
	//BSD license
	normalizeWheel : function(/*object*/ event) /*object*/ {
		// Reasonable defaults
		var PIXEL_STEP  = 10;
		var LINE_HEIGHT = 40;
		var PAGE_HEIGHT = 800;

		var sX = 0, sY = 0,       // spinX, spinY
			pX = 0, pY = 0;       // pixelX, pixelY

		// Legacy
		if ('detail'      in event) { sY = event.detail; }
		if ('wheelDelta'  in event) { sY = -event.wheelDelta / 120; }
		if ('wheelDeltaY' in event) { sY = -event.wheelDeltaY / 120; }
		if ('wheelDeltaX' in event) { sX = -event.wheelDeltaX / 120; }

		// side scrolling on FF with DOMMouseScroll
		if ('axis' in event && event.axis === event.HORIZONTAL_AXIS) {
			sX = sY;
			sY = 0;
		}

		pX = sX * PIXEL_STEP;
		pY = sY * PIXEL_STEP;

		if ('deltaY' in event) { pY = event.deltaY; }
		if ('deltaX' in event) { pX = event.deltaX; }

		if ((pX || pY) && event.deltaMode) {
			if (event.deltaMode == 1) {          // delta in LINE units
				pX *= LINE_HEIGHT;
				pY *= LINE_HEIGHT;
			} else {                             // delta in PAGE units
				pX *= PAGE_HEIGHT;
				pY *= PAGE_HEIGHT;
			}
		}

		// Fall-back if spin cannot be determined
		if (pX && !sX) { sX = (pX < 1) ? -1 : 1; }
		if (pY && !sY) { sY = (pY < 1) ? -1 : 1; }

		return {
			spinX  : sX,
			spinY  : sY,
			pixelX : pX,
			pixelY : pY,
			deltaMode : (event.deltaMode || 0),
			};
	},
};
