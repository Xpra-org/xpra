/*
 * This file is part of Xpra.
 * Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2016 Spikes, Inc.
 * Licensed under MPL 2.0, see:
 * http://www.mozilla.org/MPL/2.0/
 *
 */

'use strict';

var Utilities = {
	VERSION	: "1.0.4",

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
};
