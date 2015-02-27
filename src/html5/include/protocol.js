/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Licensed under MPL 2.0
 *
 * xpra wire protocol
 *
 * provides a higher level API wrapping websock,
 * more similar to the python version of xpra.
 *
 * requires the following javascript imports:
 * - websock.js		: fast binary websockets
 * - bencode.js		: bencoder
 * - inflate.min.js	: zlib inflate
 * - deflate.min.js : zlib deflate - do not use, broken!
 *
 * instead of using the WebSocket object directly, it wraps
 * the Websock object which adds more robust recieve queue
 * buffering
 */


function Protocol() {
"use strict";

var api = {},         // Public API
	ws,
	raw_packets = {},
	packet_handlers = {},
	log_packets = true,
	no_log_packet_types = ["ping_echo", "key-action", "damage-sequence",
	                       "map-window", "configure-window", "close-window",
	                       "desktop_size", "hello",
	                       "pointer-position", "button-action", "focus"];


function debug(msg) {
	console.log(msg);
}
function error(msg) {
	console.error(msg);
}

//
// Private utility routines
//
function hex2(i) {
	"use strict";
	var s = i.toString(16);
	if (s.length<2)
		s = "0"+s;
	return s;
}
function hexstr(uintArray) {
	"use strict";
	var s = "";
	for (var i=0; i<uintArray.byteLength; i++) {
		s += hex2(uintArray[i]);
	}
	return s;
}


//got a packet from websock:
function on_message() {
	"use strict";
	// websock on_message event is simply a notification
	// that data is available on the recieve queue
	// check for 8 bytes on buffer
	if(ws.rQwait("", 8, 0) == false) {
		//got a complete header, try and parse
		process_buffer();
	}
}

//hook websock events using packet handlers:
function on_open() {
	//debug("on_open("+m+")");
	process_packet(["open"]);
}
function on_close(e) {
	//show("on_close("+m+")");
	process_packet(["close"]);
}
function on_error(e) {
	//show("on_error("+m+")");
	process_packet(["error"]);
}

//we have enough bytes for a header, try to parse:
function process_buffer() {
	"use strict";
	//debug("peeking at first 8 bytes of buffer...")
	var buf = ws.rQpeekBytes(8);

	if (buf[0]!=ord("P")) {
		throw "invalid packet header format: "+hex2(buf[0]);
	}

	var proto_flags = buf[1];
	if (proto_flags!=0) {
		throw "we cannot handle any protocol flags yet, sorry";
	}
	var level = buf[2];
	var index = buf[3];
	var packet_size = 0;
	for (var i=0; i<4; i++) {
		//debug("size header["+i+"]="+buf[4+i]);
		packet_size = packet_size*0x100;
		packet_size += buf[4+i];
	}
	//debug("packet_size="+packet_size+", level="+level+", index="+index);

	// wait for packet to be complete
	// the header is still on the buffer so wait for packetsize+headersize bytes!
	if (wsock.rQlen() < packet_size+8) {
		// we already shifted the header off the buffer?
		debug("packet is not complete yet");
		return;
	}

	// packet is complete but header is still on buffer
	ws.rQshiftBytes(8);
	//debug("got a full packet, shifting off "+packet_size);
	var packet_data = ws.rQshiftBytes(packet_size);

	//decompress it if needed:
	if (level!=0) {
		var inflated = new Zlib.Inflate(packet_data).decompress();
		//debug("inflated("+packet_data+")="+inflated);
		packet_data = inflated;
	}

	//save it for later? (partial raw packet)
	if (index>0) {
		//debug("added raw packet for index "+index);
		raw_packets[index] = packet_data;
		return;
	}

	//decode raw packet string into objects:
	var packet = null;
	try {
		packet = bdecode(packet_data);
		for (var index in raw_packets) {
			packet[index] = raw_packets[index];
		}
		raw_packets = {};
		process_packet(packet);
	}
	catch (e) {
		debug("error processing packet: "+e);
		debug("packet_data="+packet_data);
	}

	// see if buffer still has unread packets
	if (ws.rQlen() > 8) {
		process_buffer();
	}

}

function process_packet(packet) {
	"use strict";

	var packet_type = "";
	var fn = "";
	try {
		packet_type = packet[0];
		show("received a " + packet_type + " packet");
		fn = packet_handlers[packet_type];
		if (fn==undefined)
			error("no packet handler for "+packet_type+"!");
		else
			fn(packet);
	}
	catch (e) {
		error("error processing '"+packet_type+"' with '"+fn+"': "+e);
		throw e;
	}
}


//
// Public functions
//

//send a packet:
function send(packet) {
	"use strict";

	var bdata = bencode(packet);
	//convert string to a byte array:
	var cdata = [];
	for (var i=0; i<bdata.length; i++)
		cdata.push(ord(bdata[i]));
	var level = 0;
	/*
	var use_zlib = false;		//does not work...
	if (use_zlib) {
		cdata = new Zlib.Deflate(cdata).compress();
		level = 1;
	}*/
	var len = cdata.length;
	//struct.pack('!BBBBL', ord("P"), proto_flags, level, index, payload_size)
	var header = ["P".charCodeAt(0), 0, level, 0];
	for (var i=3; i>=0; i--)
		header.push((len >> (8*i)) & 0xFF);
	//concat data to header, saves an intermediate array which may or may not have
	//been optimised out by the JS compiler anyway, but it's worth a shot
	header = header.concat(cdata);
	//debug("send("+packet+") "+data.byteLength+" bytes in packet for: "+bdata.substring(0, 32)+"..");
	ws.send(header);
}



// Set event handlers
function set_packet_handler(packet_type, handler) {
	"use strict";
	packet_handlers[packet_type] = handler;
}

function open(uri) {
	"use strict";
	if (ws!=null) {
		debug("opening a new uri, closing current websocket connection");
		close();
	}
	ws = new Websock();
	ws.on('open', on_open);
	ws.on('close', on_close);
	ws.on('error', on_error);
	ws.on('message', on_message);
	ws.open(uri, ['binary']);
}

function close() {
	"use strict";
	if (ws!=null) {
		ws.close();
		ws = null;
	}
}


function constructor() {
	"use strict";
	api.open				= open;
    api.send				= send;
    api.set_packet_handler	= set_packet_handler;
	api.close				= close;

    return api;
}

return constructor();

}
