/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2014 Joshua Higgins <josh@kxes.net>
 * Licensed under MPL 2.0
 *
 * xpra wire protocol HTML5 web worker
 *
 * requires the following javascript imports:
 * - websock.js     : binary websockets (xpra modified version)
 * - bencode.js		: bencoder (xpra modified version)
 * - inflate.min.js	: zlib inflate
 * - deflate.min.js : zlib deflate - do not use, broken!
 */

 // worker imports are relative to worker script path
 importScripts('websock.js',
 	'bencode.js',
 	'inflate.min.js',
 	'deflate.min.js');


// global to worker
var wsock;
var raw_packets = {};


//
// Listen for messages posted to the worker
//
self.addEventListener('message', function(e) {
	var data = e.data;
	switch (data.cmd) {
	case 'open':
		init(data.uri);
		break;
	case 'send':
		send(data.packet);
		break;
	case 'close':
		if (wsock) {
			wsock.close();
		}
		self.close(); // terminate the worker
		break;
	default:
		debug("worker got unknown message");
	};
}, false);


//
// initialise Websock connection
//
function init(uri) {
	"use strict";
	debug("connecting websocket");
	wsock = new Websock();
	wsock.on('open', on_open);
	wsock.on('close', on_close);
	wsock.on('error', on_error);
	wsock.on('message', on_message);
	wsock.open(uri, ['binary']);
}

function on_open() {
	//tell client connection has opened
	self.postMessage({'cmd': 'open'});
}

function on_close(e) {
	//tell client connection has closed
	wsock = null;
	self.postMessage({'cmd': 'close'});
}

function on_error(e) {
	//tell client connection has error
	self.postMessage({'cmd': 'error'});
}

function on_message() {
	//wait for a header
	if(wsock.rQwait("", 8, 0) == false) {
		//got a complete header, try and parse
		process_buffer();
	}
}


function process_buffer() {
	"use strict";
	//debug("peeking at first 8 bytes of buffer...")
	var buf = wsock.rQpeekBytes(8);

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
	if (wsock.rQlen() < packet_size-8) {
		// we already shifted the header off the buffer?
		debug("packet is not complete yet");
		return;
	}

	// packet is complete but header is still on buffer
	wsock.rQshiftBytes(8);
	//debug("got a full packet, shifting off "+packet_size);
	var packet_data = wsock.rQshiftBytes(packet_size);

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
		/* we don't use transferable object here for a few reasons
		 * 1) Only an ArrayBuffer implements the 'Transferable' interface
		 * 2) The burden of decoding and inflating must be taken by the worker
		 * 3) The object copy is performed by the worker so it doesn't block the UI
		 * 4) Serialising packet object to JSON > String > ArrayBuffer and back is probably slower than the copy
		 */
		//debug("recieved worker:"+packet);
		raw_packets = {}
		self.postMessage({'cmd': 'process', 'packet': packet});
	}
	catch (e) {
		debug("error processing packet: "+e);
		debug("packet_data="+packet_data);
	}

	// see if buffer still has unread packets
	if (wsock.rQlen() > 8) {
		process_buffer();
	}

}

//send a packet:
function send(packet) {
	"use strict";
	//debug("send worker:"+packet);
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
	wsock.send(header);
}