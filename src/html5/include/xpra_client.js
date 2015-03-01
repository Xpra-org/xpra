/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2014 Joshua Higgins <josh@kxes.net>
 * Copyright (c) 2015 Spikes, Inc.
 * Licensed under MPL 2.0
 *
 * xpra client
 *
 * requires:
 *	xpra_protocol.js
 *  keycodes.js
 */

XPRA_CLIENT_FORCE_NO_WORKER = true;

function XpraClient(container) {
	// state
	this.host = null;
	this.port = null;
	this.ssl = null;
	// some client stuff
	this.OLD_ENCODING_NAMES_TO_NEW = {"x264" : "h264", "vpx" : "vp8"};
	this.RGB_FORMATS = ["RGBX", "RGBA"];
	this.caps_lock = null;
	this.alt_modifier = null;
	this.meta_modifier = null;
	// the container div is the "screen" on the HTML page where we
	// are able to draw our windows in.
	this.container = document.getElementById(container);
	if(!this.container) {
		throw "invalid container element";
	}
	// a list of our windows
	this.id_to_window = {};
	// the protocol
	this.protocol = null;
	// the client holds a list of packet handlers
	this.packet_handlers = {
		'open': this._process_open,
		'startup-complete': this._process_startup_complete,
		'hello': this._process_hello,
		'ping': this._process_ping
	};
}

XpraClient.prototype.connect = function(host, port, ssl) {
	// open the web socket, started it in a worker if available
	console.log("connecting to xpra server " + host + ":" + port + " with ssl: " + ssl);
	this.host = host;
	this.port = port;
	this.ssl = ssl;
	// detect websocket in webworker support and degrade gracefully
	if(window.Worker) {
		console.log("we have webworker support");
		// spawn worker that checks for a websocket
		var me = this;
		var worker = new Worker('include/wsworker_check.js');
		worker.addEventListener('message', function(e) {
			var data = e.data;
			switch (data['result']) {
				case true:
				// yey, we can use websocket in worker!
				console.log("we can use websocket in webworker");
				me._do_connect(true);
				break;
				case false:
				console.log("we can't use websocket in webworker, won't use webworkers");
				break;
				default:
				console.log("client got unknown message from worker");
			};
		}, false);
		// ask the worker to check for websocket support, when we recieve a reply
		// through the eventlistener above, _do_connect() will finish the job
		worker.postMessage({'cmd': 'check'});
	} else {
		// no webworker support
		console.log("no webworker support at all.")
	}
}

XpraClient.prototype._do_connect = function(with_worker) {
	if(with_worker && !(XPRA_CLIENT_FORCE_NO_WORKER)) {
		this.protocol = new XpraProtocolWorkerHost();
	} else {
		this.protocol = new XpraProtocol();
	}
	// set protocol to deliver packets to our packet router
	this.protocol.set_packet_handler(this._route_packet, this);
	// make uri
	var uri = "ws://";
	if (this.ssl)
		uri = "wss://";
	uri += this.host;
	uri += ":" + this.port;
	// do open
	this.protocol.open(uri);
}

XpraClient.prototype.close = function() {
	// close all windows
	// close protocol
	this.protocol.close();
}

XpraClient.prototype._route_packet = function(packet, ctx) {
	// ctx refers to `this` because we came through a callback
	var packet_type = "";
	var fn = "";
	try {
		packet_type = packet[0];
		console.log("received a " + packet_type + " packet");
		fn = ctx.packet_handlers[packet_type];
		if (fn==undefined)
			console.error("no packet handler for "+packet_type+"!");
		else
			fn(packet, ctx);
	}
	catch (e) {
		console.error("error processing '"+packet_type+"' with '"+fn+"': "+e);
		throw e;
	}
}

XpraClient.prototype._guess_platform_processor = function() {
	//mozilla property:
	if (navigator.oscpu)
		return navigator.oscpu;
	//ie:
	if (navigator.cpuClass)
		return navigator.cpuClass;
	return "unknown";
}

XpraClient.prototype._guess_platform_name = function() {
	//use python style strings for platforms:
	if (navigator.appVersion.indexOf("Win")!=-1)
		return "Microsoft Windows";
	if (navigator.appVersion.indexOf("Mac")!=-1)
		return "Mac OSX";
	if (navigator.appVersion.indexOf("Linux")!=-1)
		return "Linux";
	if (navigator.appVersion.indexOf("X11")!=-1)
		return "Posix";
	return "unknown";
}

XpraClient.prototype._guess_platform = function() {
	//use python style strings for platforms:
	if (navigator.appVersion.indexOf("Win")!=-1)
		return "win32";
	if (navigator.appVersion.indexOf("Mac")!=-1)
		return "darwin";
	if (navigator.appVersion.indexOf("Linux")!=-1)
		return "linux2";
	if (navigator.appVersion.indexOf("X11")!=-1)
		return "posix";
	return "unknown";
}

XpraClient.prototype._get_keyboard_layout = function() {
	//IE:
	//navigator.systemLanguage
	//navigator.browserLanguage
	var v = window.navigator.userLanguage || window.navigator.language;
	//ie: v="en_GB";
	v = v.split(",")[0];
	var l = v.split("-", 2);
	if (l.length==1)
		l = v.split("_", 2);
	if (l.length==1)
		return "";
	//ie: "gb"
	return l[1].toLowerCase();
}

XpraClient.prototype._get_keycodes = function() {
	//keycodes.append((nn(keyval), nn(name), nn(keycode), nn(group), nn(level)))
	var keycodes = [];
	var kc;
	for(var keycode in CHARCODE_TO_NAME) {
		kc = parseInt(keycode);
		keycodes.push([kc, CHARCODE_TO_NAME[keycode], kc, 0, 0]);
	}
	//show("keycodes="+keycodes.toSource());
	return keycodes;
}

XpraClient.prototype._get_desktop_size = function() {
	return [this.container.clientWidth, this.container.clientHeight];
}

XpraClient.prototype._get_DPI = function() {
	"use strict";
	var dpi_div = document.getElementById("dpi");
	if (dpi_div != undefined) {
		//show("dpiX="+dpi_div.offsetWidth+", dpiY="+dpi_div.offsetHeight);
		if (dpi_div.offsetWidth>0 && dpi_div.offsetHeight>0)
			return Math.round((dpi_div.offsetWidth + dpi_div.offsetHeight) / 2.0);
	}
	//alternative:
	if ('deviceXDPI' in screen)
		return (screen.systemXDPI + screen.systemYDPI) / 2;
	//default:
	return 96;
}

XpraClient.prototype._get_screen_sizes = function() {
	var dpi = this._get_DPI();
	var screen_size = this._get_desktop_size();
	var wmm = Math.round(screen_size[0]*25.4/dpi);
	var hmm = Math.round(screen_size[1]*25.4/dpi);
	var monitor = ["Canvas", 0, 0, screen_size[0], screen_size[1], wmm, hmm];
	var screen = ["HTML", screen_size[0], screen_size[1],
				wmm, hmm,
				[monitor],
				0, 0, screen_size[0], screen_size[1]
			];
	//just a single screen:
	return [screen];
}

XpraClient.prototype._make_hello = function() {
	return {
		"version"					: "0.15.0",
		"platform"					: this._guess_platform(),
		"platform.name"				: this._guess_platform_name(),
		"platform.processor"		: this._guess_platform_processor(),
		"platform.platform"			: navigator.appVersion,
		"namespace"			 		: true,
		"client_type"		   		: "HTML5",
		"share"						: false,
		"auto_refresh_delay"		: 500,
		"randr_notify"				: true,
		"sound.server_driven"		: true,
		"generic_window_types"		: true,
		"server-window-resize"		: true,
		"notify-startup-complete"	: true,
		"generic-rgb-encodings"		: true,
		"window.raise"				: true,
		"encodings"					: ["rgb"],
		"raw_window_icons"			: true,
		//rgb24 is not efficient in HTML so don't use it:
		//png and jpeg will need extra code
		//"encodings.core"			: ["rgb24", "rgb32", "png", "jpeg"],
		"encodings.core"			: ["rgb32"],
		"encodings.rgb_formats"	 	: this.RGB_FORMATS,
		"encoding.generic"	  		: true,
		"encoding.transparency"		: true,
		"encoding.client_options"	: true,
		"encoding.csc_atoms"		: true,
		"encoding.uses_swscale"		: false,
		//video stuff we may handle later:
		"encoding.video_reinit"		: false,
		"encoding.video_scaling"	: false,
		"encoding.csc_modes"		: [],
		//sound (not yet):
		"sound.receive"				: false,
		"sound.send"				: false,
		//compression bits:
		"zlib"						: true,
		"lz4"						: false,
		"compression_level"	 		: 1,
		"compressible_cursors"		: true,
		"encoding.rgb24zlib"		: true,
		"encoding.rgb_zlib"			: true,
		"encoding.rgb_lz4"			: false,
		"windows"					: true,
		//partial support:
		"keyboard"					: true,
		"xkbmap_layout"				: this._get_keyboard_layout(),
		"xkbmap_keycodes"			: this._get_keycodes(),
		"desktop_size"				: this._get_desktop_size(),
		"screen_sizes"				: this._get_screen_sizes(),
		"dpi"						: this._get_DPI(),
		//not handled yet, but we will:
		"clipboard_enabled"			: false,
		"notifications"				: true,
		"cursors"					: true,
		"bell"						: true,
		"system_tray"				: true,
		//we cannot handle this (GTK only):
		"named_cursors"				: false,
	};
}

XpraClient.prototype._process_open = function(packet, ctx) {
	console.log("sending hello");
	var hello = ctx._make_hello();
	ctx.protocol.send(["hello", hello]);
}

XpraClient.prototype._process_startup_complete = function(packet, ctx) {
	console.log("startup complete");
}

XpraClient.prototype._process_hello = function(packet, ctx) {
	//show("process_hello("+packet+")");
	var hello = packet[1];
	var version = hello["version"];
	try {
		var vparts = version.split(".");
		var vno = [];
		for (var i=0; i<vparts.length;i++) {
			vno[i] = parseInt(vparts[i]);
		}
		if (vno[0]<=0 && vno[1]<10) {
			throw "unsupported version: " + version;
			this.close();
			return;
		}
	}
	catch (e) {
		throw "error parsing version number '" + version + "'";
		this.close();
		return;
	}
	console.log("got hello: server version "+version+" accepted our connection");
	//figure out "alt" and "meta" keys:
	if ("modifier_keycodes" in hello) {
		var modifier_keycodes = hello["modifier_keycodes"];
		for (var mod in modifier_keycodes) {
			//show("modifier_keycode["+mod+"]="+modifier_keycodes[mod].toSource());
			var keys = modifier_keycodes[mod];
			for (var i=0; i<keys.length; i++) {
				var key = keys[i];
				//the first value is usually the integer keycode,
				//the second one is the actual key name,
				//doesn't hurt to test both:
				for (var j=0; j<key.length; j++) {
					if ("Alt_L"==key[j])
						this.alt_modifier = mod;
					if ("Meta_L"==key[j])
						this.meta_modifier = mod;
				}
			}
		}
	}
	//show("alt="+alt_modifier+", meta="+meta_modifier);
}

XpraClient.prototype._process_ping = function(packet, ctx) {
	var echotime = packet[1];
	var l1=0, l2=0, l3=0;
	ctx.protocol.send(["ping_echo", echotime, l1, l2, l3, 0]);
}