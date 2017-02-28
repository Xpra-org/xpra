/*
 * Copyright (c) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2016 David Brushinski <dbrushinski@spikes.com>
 * Copyright (c) 2014 Joshua Higgins <josh@kxes.net>
 * Copyright (c) 2015 Spikes, Inc.
 * Portions based on websock.js by Joel Martin
 * Copyright (C) 2012 Joel Martin
 *
 * Licensed under MPL 2.0
 *
 * xpra wire protocol with worker support
 *
 * requires:
 *	bencode.js
 *  inflate.js
 *  lz4.js
 */


/*
A stub class to facilitate communication with the protocol when
it is loaded in a worker
*/
function XpraProtocolWorkerHost() {
	this.worker = null;
	this.packet_handler = null;
	this.packet_ctx = null;
}

XpraProtocolWorkerHost.prototype.open = function(uri) {
	var me = this;
	this.worker = new Worker('js/Protocol.js');
	this.worker.addEventListener('message', function(e) {
		var data = e.data;
		switch (data.c) {
			case 'r':
				me.worker.postMessage({'c': 'o', 'u': uri});
				break;
			case 'p':
				if(me.packet_handler) {
					me.packet_handler(data.p, me.packet_ctx);
				}
				break;
			case 'l':
				console.log(data.t);
				break;
		default:
			console.error("got unknown command from worker");
			console.error(e.data);
		};
	}, false);
}

XpraProtocolWorkerHost.prototype.close = function() {
	this.worker.postMessage({'c': 'c'});
}

XpraProtocolWorkerHost.prototype.terminate = function() {
	this.worker.postMessage({'c': 't'});
}

XpraProtocolWorkerHost.prototype.send = function(packet) {
	this.worker.postMessage({'c': 's', 'p': packet});
}

XpraProtocolWorkerHost.prototype.set_packet_handler = function(callback, ctx) {
	this.packet_handler = callback;
	this.packet_ctx = ctx;
}

XpraProtocolWorkerHost.prototype.set_cipher_in = function(caps, key) {
	this.worker.postMessage({'c': 'z', 'p': caps, 'k': key});
}

XpraProtocolWorkerHost.prototype.set_cipher_out = function(caps, key) {
	this.worker.postMessage({'c': 'x', 'p': caps, 'k': key});
}



/*
The main Xpra wire protocol
*/
function XpraProtocol() {
	this.is_worker = false;
	this.packet_handler = null;
	this.packet_ctx = null;
	this.websocket = null;
	this.raw_packets = [];
	this.cipher_in = null;
	this.cipher_in_block_size = null;
	this.cipher_out = null;
	this.rQ = [];			// Receive queue
	this.sQ = [];			// Send queue
	this.mQ = [];			// Worker message queue
	this.header = [];

	//Queue processing via intervals
	this.process_interval = 0;  //milliseconds
}

XpraProtocol.prototype.open = function(uri) {
	var me = this;
	// init
	this.rQ		 = [];
	this.sQ		 = [];
	this.websocket  = null;
	// connect the socket
	this.websocket = new WebSocket(uri, 'binary');
	this.websocket.binaryType = 'arraybuffer';
	this.websocket.onopen = function () {
		me.packet_handler(['open'], me.packet_ctx);
	};
	this.websocket.onclose = function () {
		me.packet_handler(['close'], me.packet_ctx);
	};
	this.websocket.onerror = function () {
		me.packet_handler(['error'], me.packet_ctx);
	};
	this.websocket.onmessage = function (e) {
		// push arraybuffer values onto the end
		me.rQ.push(new Uint8Array(e.data));
		setTimeout(function() {
				me.process_receive_queue();
			}, this.process_interval);
	};
	this.start_processing();
}

XpraProtocol.prototype.close = function() {
	this.stop_processing();
	this.websocket.close();
}

XpraProtocol.prototype.terminate = function() {
	this.stop_processing();
	// if this is called here we are not in a worker, so
	// do nothing
	return;
}

XpraProtocol.prototype.start_processing = function() {
}
XpraProtocol.prototype.stop_processing = function() {
}


XpraProtocol.prototype.process_receive_queue = function() {
	var i = 0, j = 0;
	if (this.header.length<8 && this.rQ.length>0) {
		//add from receive queue data to header until we get the 8 bytes we need:
		while (this.header.length<8 && this.rQ.length>0) {
			var slice = this.rQ[0];
			var needed = 8-this.header.length;
			var n = Math.min(needed, slice.length);
			//console.log("header size", this.header.length, ", adding", n, "bytes from", slice.length);
			//copy at most n characters:
			for (i = 0; i < n; i++) {
				this.header.push(slice[i]);
			}
			if (slice.length>needed) {
				//replace the slice with what is left over:
				this.rQ[0] = slice.subarray(n);
			}
			else {
				//this slice has been fully consumed already:
				this.rQ.shift();
			}
		}

		//verify the header format:
		if (this.header[0] !== ord("P")) {
			msg = "invalid packet header format: " + this.header[0];
			if (this.header.length>1) {
				msg += ": ";
				for (c in this.header) {
					msg += String.fromCharCode(c);
				}
			}
			throw msg;
		}
	}

	if (this.header.length<8) {
		//we need more data to continue
		return;
	}

	var proto_flags = this.header[1];
	var proto_crypto = proto_flags & 0x2;
	if (proto_flags!=0) {
		// check for crypto protocol flag
		if (!(proto_crypto)) {
			throw "we can't handle this protocol flag yet, sorry";
		}
	}

	var level = this.header[2];
	if (level & 0x20) {
		throw "lzo compression is not supported";
	}
	var index = this.header[3];
	if (index>=20) {
		throw "invalid packet index: "+index;
	}
	var packet_size = 0;
	for (i=0; i<4; i++) {
		packet_size = packet_size*0x100;
		packet_size += this.header[4+i];
	}

	// work out padding if necessary
	var padding = 0
	if (proto_crypto) {
		padding = (this.cipher_in_block_size - packet_size % this.cipher_in_block_size);
		packet_size += padding;
	}

	// verify that we have enough data for the full payload:
	var rsize = 0;
	for (i=0,j=this.rQ.length;i<j;++i) {
		rsize += this.rQ[i].length;
	}
	if (rsize<packet_size) {
		return;
	}

	// done parsing the header, the next packet will need a new one:
	this.header = []

	var packet_data = null;
	if (this.rQ[0].length==packet_size) {
		//exact match: the payload is in a buffer already:
		packet_data = this.rQ.shift();
	}
	else {
		//aggregate all the buffers into "packet_data" until we get exactly "packet_size" bytes:
		packet_data = new Uint8Array(packet_size);
		rsize = 0;
		while (rsize < packet_size) {
			var slice = this.rQ[0];
			var needed = packet_size - rsize;
			//console.log("slice:", slice.length, "bytes, needed", needed);
			if (slice.length>needed) {
				//add part of this slice:
				packet_data.set(slice.subarray(0, needed), rsize);
				rsize += needed;
				this.rQ[0] = slice.subarray(needed);
			}
			else {
				//add this slice in full:
				packet_data.set(slice, rsize);
				rsize += slice.length;
				this.rQ.shift();
			}
		}
	}

	// decrypt if needed
	if (proto_crypto) {
		this.cipher_in.update(forge.util.createBuffer(uintToString(packet_data)));
		var decrypted = this.cipher_in.output.getBytes();
		packet_data = [];
		for (i=0; i<decrypted.length; i++)
			packet_data.push(decrypted[i].charCodeAt(0));
		packet_data = packet_data.slice(0, -1 * padding);
	}

	//decompress it if needed:
	if (level!=0) {
		if (level & 0x10) {
			// lz4
			// python-lz4 inserts the length of the uncompressed data as an int
			// at the start of the stream
			var d = packet_data.subarray(0, 4);
			// output buffer length is stored as little endian
			var length = d[0] | (d[1] << 8) | (d[2] << 16) | (d[3] << 24);
			// decode the LZ4 block
			// console.log("lz4 decompress packet size", packet_size, ", lz4 length=", length);
			var inflated = new Uint8Array(length);
			var uncompressedSize = LZ4.decodeBlock(packet_data, inflated, 4);
			// if lz4 errors out at the end of the buffer, ignore it:
			if (uncompressedSize<=0 && packet_size+uncompressedSize!=0) {
				console.error("failed to decompress lz4 data, error code:", uncompressedSize);
				return;
			}
		} else {
			// zlib
			var inflated = new Zlib.Inflate(packet_data).decompress();
		}
		//debug("inflated("+packet_data+")="+inflated);
		packet_data = inflated;
	}

	//save it for later? (partial raw packet)
	if (index>0) {
		//debug("added raw packet for index "+index);
		this.raw_packets[index] = packet_data;
	} else {
		//decode raw packet string into objects:
		var packet = null;
		try {
			packet = bdecode(packet_data);
			for (var index in this.raw_packets) {
				packet[index] = this.raw_packets[index];
			}
			this.raw_packets = {}
			// pass to our packet handler
			if((packet[0] === 'draw') && (packet[6] !== 'scroll')){
				var img_data = packet[7];
				if (typeof img_data === 'string') {
					var uint = new Uint8Array(img_data.length);
					for(i=0,j=img_data.length;i<j;++i) {
						uint[i] = img_data.charCodeAt(i);
					}
					packet[7] = uint;
				}
			}
			if (this.is_worker){
				this.mQ[this.mQ.length] = packet;
				var me = this;
				setTimeout(function() {
						me.process_message_queue();
					}, this.process_interval);
			} else {
				this.packet_handler(packet, this.packet_ctx);
			}
		}
		catch (e) {
			console.error("error processing packet " + e)
			//console.error("packet_data="+packet_data);
		}
	}
}

XpraProtocol.prototype.process_send_queue = function() {
	while(this.sQ.length !== 0) {
		var packet = this.sQ.shift();
		if(!packet){
			return;
		}

		//debug("send worker:"+packet);
		var bdata = bencode(packet);
		var proto_flags = 0;
		var payload_size = bdata.length;
		// encryption
		if(this.cipher_out) {
			proto_flags = 0x2;
			var padding_size = this.cipher_out_block_size - (payload_size % this.cipher_out_block_size);
			for (var i = padding_size - 1; i >= 0; i--) {
				bdata += String.fromCharCode(padding_size);
			};
			this.cipher_out.update(forge.util.createBuffer(bdata));
			bdata = this.cipher_out.output.getBytes();
		}
		var actual_size = bdata.length;
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
		//struct.pack('!BBBBL', ord("P"), proto_flags, level, index, payload_size)
		var header = ["P".charCodeAt(0), proto_flags, level, 0];
		for (var i=3; i>=0; i--)
			header.push((payload_size >> (8*i)) & 0xFF);
		//concat data to header, saves an intermediate array which may or may not have
		//been optimised out by the JS compiler anyway, but it's worth a shot
		header = header.concat(cdata);
		//debug("send("+packet+") "+cdata.length+" bytes in packet for: "+bdata.substring(0, 32)+"..");
		// put into buffer before send
		this.websocket.send((new Uint8Array(header)).buffer);
	}
}

XpraProtocol.prototype.process_message_queue = function() {
	while(this.mQ.length !== 0){
		var packet = this.mQ.shift();

		if(!packet){
			return;
		}

		var raw_draw_buffer = (packet[0] === 'draw') && (packet[6] !== 'scroll');
		postMessage({'c': 'p', 'p': packet}, raw_draw_buffer ? [packet[7].buffer] : []);
	}
}

XpraProtocol.prototype.send = function(packet) {
	this.sQ[this.sQ.length] = packet;
	var me = this;
	setTimeout(function() {
		me.process_send_queue();
		}, this.process_interval);
}

XpraProtocol.prototype.set_packet_handler = function(callback, ctx) {
	this.packet_handler = callback;
	this.packet_ctx = ctx;
}

XpraProtocol.prototype.set_cipher_in = function(caps, key) {
	this.cipher_in_block_size = 32;
	// stretch the password
	var secret = forge.pkcs5.pbkdf2(key, caps['cipher.key_salt'], caps['cipher.key_stretch_iterations'], this.cipher_in_block_size);
	// start the cipher
	this.cipher_in = forge.cipher.createDecipher('AES-CBC', secret);
	this.cipher_in.start({iv: caps['cipher.iv']});
}

XpraProtocol.prototype.set_cipher_out = function(caps, key) {
	this.cipher_out_block_size = 32;
	// stretch the password
	var secret = forge.pkcs5.pbkdf2(key, caps['cipher.key_salt'], caps['cipher.key_stretch_iterations'], this.cipher_out_block_size);
	// start the cipher
	this.cipher_out = forge.cipher.createCipher('AES-CBC', secret);
	this.cipher_out.start({iv: caps['cipher.iv']});
}


/*
If we are in a web worker, set up an instance of the protocol
*/
if (!(typeof window == "object" && typeof document == "object" && window.document === document)) {
	// some required imports
	// worker imports are relative to worker script path
	importScripts(
		'lib/bencode.js',
		'lib/zlib.js',
		'lib/lz4.js',
		'lib/forge.js');
	// make protocol instance
	var protocol = new XpraProtocol();
	protocol.is_worker = true;
	// we create a custom packet handler which posts packet as a message
	protocol.set_packet_handler(function (packet, ctx) {
		var raw_draw_buffer = (packet[0] === 'draw') && (packet[6] !== 'scroll');
		postMessage({'c': 'p', 'p': packet}, raw_draw_buffer ? [packet[7].buffer] : []);
	}, null);
	// attach listeners from main thread
	self.addEventListener('message', function(e) {
		var data = e.data;
		switch (data.c) {
		case 'o':
			protocol.open(data.u);
			break;
		case 's':
			protocol.send(data.p);
			break;
		case 'x':
			protocol.set_cipher_out(data.p, data.k);
			break;
		case 'z':
			protocol.set_cipher_in(data.p, data.k);
			break;
		case 'c':
			// close the connection
			protocol.close();
			break;
		case 't':
			// terminate the worker
			self.close();
			break;
		default:
			postMessage({'c': 'l', 't': 'got unknown command from host'});
		};
	}, false);
	// tell host we are ready
	postMessage({'c': 'r'});
}


// initialise LZ4 library
var Buffer = require('buffer').Buffer;
var LZ4 = require('lz4');
