/*
 * Copyright (c) 2013 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2014 Joshua Higgins <josh@kxes.net>
 * Licensed under MPL 2.0
 *
 * xpra wire protocol
 *
 * provides a higher level API wrapping the 
 * protocol_worker based on websock
 */


function Protocol() {
"use strict";

var api = {},         // Public API
	worker,
	packet_handlers = {};


function debug(msg) {
	console.log(msg);
}
function error(msg) {
	console.error(msg);
}

function process_packet(packet) {
	"use strict";

	var packet_type = "";
	var fn = "";
	try {
		packet_type = packet[0];
		//show("received a " + packet_type + " packet");
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
	//debug("send protocol:"+packet);
	worker.postMessage({'cmd': 'send', 'packet': packet});
}

// Set event handlers
function set_packet_handler(packet_type, handler) {
	"use strict";
	packet_handlers[packet_type] = handler;
}

function open(uri) {
	"use strict";
	// start web worker
	worker = new Worker('include/protocol_worker.js');
	worker.addEventListener('message', function(e) {
		var data = e.data;
		switch (data.cmd) {
		case 'open':
			process_packet(['open']);
			break;
		case 'close':
			process_packet(['close']);
			break;
		case 'error':
			process_packet(['error']);
			break;
		case 'process':
			process_packet(data.packet);
			break;
		default:
			debug("client got unknown message from worker");
		};
	}, false);
	worker.postMessage({'cmd': 'open', 'uri': uri});
}

function close() {
	"use strict";
	// tell worker to close
	worker.postMessage({'cmd': 'close'});
}


function constructor() {
	"use strict";
	api.open				= open;
    api.send				= send;
    api.set_packet_handler	= set_packet_handler;
	api.close				= close;
	api.worker 				= worker;

    return api;
}

return constructor();

}
