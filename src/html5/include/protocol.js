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
 * - websock.js		: websockets
 * - bencode.js		: bencoder
 * - inflate.min.js	: zlib inflate
 * - deflate.min.js : zlib deflate - do not use, broken!
 */


function Protocol() {
"use strict";

var api = {},         // Public API
	ws,
	buf = "",
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


//
// websocket glue functions
//

//got a packet from websock:
function on_message(m) {
	"use strict";
	var blob = m.data;
	var reader = new FileReader()
	reader.onload = function(evt) {
		var result = new Uint8Array(this.result);
		process_bytes(result);
	}
	reader.readAsArrayBuffer(blob);
}

//hook websock events using packet handlers:
function on_open(m) {
	//debug("on_open("+m+")");
	process_packet(["open", m]);
}
function on_close(m) {
	//show("on_close("+m+")");
	process_packet(["close", m]);
}
function on_error(m) {
	//show("on_error("+m+")");
	process_packet(["error", m]);
}


//process some bytes we have received:
function process_bytes(bytearray) {
	"use strict";

	//debug("process_bytes("+bytearray.byteLength+" bytes)");
	//add to existing buffer:
	var tmp = new Uint8Array(buf.length + bytearray.byteLength);
	if (buf.length>0)
		tmp.set(buf, 0);
	tmp.set(bytearray, buf.length);
	buf = tmp;
	if (buf.byteLength>8)
		process_buffer();
}

//we have enough bytes for a header, try to parse:
function process_buffer() {
	"use strict";

	if (buf[0]!=ord("P"))
		throw "invalid packet header format: "+hex2(buf[0]);

	var proto_flags = buf[1];
	if (proto_flags!=0)
		throw "we cannot handle any protocol flags yet, sorry";
	var level = buf[2];
	var index = buf[3];
	var packet_size = 0;
	for (var i=0; i<4; i++) {
		//debug("size header["+i+"]="+buf[4+i]);
		packet_size = packet_size*0x100;
		packet_size += buf[4+i];
	}
	//debug("packet_size="+packet_size+", data buffer size="+(buf.byteLength-8));
	if (buf.byteLength-8<packet_size) {
		debug("packet is not complete yet");
		return;
	}
	var packet_data = buf.subarray(8, packet_size+8);
	buf = buf.subarray(packet_size+8);

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
		//debug("packet[0]="+packet[0]);
		for (var index in raw_packets) {
			packet[index] = raw_packets[index];
		}
		raw_packets = {}
		process_packet(packet);
	}
	catch (e) {
		debug("error processing packet: "+e);
		debug("packet_data="+hexstr(packet_data));
	}
	if (buf.byteLength>8)
		process_buffer();
}

function process_packet(packet) {
	"use strict";

	var packet_type = "";
	var fn = "";
	try {
		packet_type = packet[0];
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
	var use_zlib = false;		//does not work...
	if (use_zlib) {
		cdata = new Zlib.Deflate(cdata).compress();
		level = 1;
	}
	var len = cdata.length;
	//struct.pack('!BBBBL', ord("P"), proto_flags, level, index, payload_size)
	var P = "P".charCodeAt(0);
	var header = [P, 0, level, 0];
	for (var i=3; i>=0; i--)
		header.push((len >> (8*i)) & 0xFF);

	var data = new Uint8Array(8+len);
	data.set(header);
	data.set(cdata, 8);

	if (log_packets && no_log_packet_types.indexOf(packet[0])<0)
		show("send("+packet+") "+data.byteLength+" bytes in packet for: "+bdata.substring(0, 32)+"..");
	ws.send(data);
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
	ws = new WebSocket(uri, ['binary']);
	ws.onmessage = on_message;
	ws.onopen = on_open;
	ws.onclose = on_close;
	ws.onerror = on_error;
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
