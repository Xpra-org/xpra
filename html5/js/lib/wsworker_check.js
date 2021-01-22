/*
 * Copyright (c) 2015 Joshua Higgins <josh@kxes.net>
 * Copyright (c) 2015 Spikes, Inc.
 * Licensed under MPL 2.0
 *
 * worker to detect websocket support inside webworker
 *
 */

self.addEventListener('message', function(e) {
	var data = e.data;
	switch (data.cmd) {
	case 'check':
		try {
			if(WebSocket) {
				self.postMessage({'result': true});
			} else {
				self.postMessage({'result': false});
			}
		} catch(err) {
			self.postMessage({'result': false});
		}
		break;
	default:
		console.log("worker got unknown message: "+data.cmd);
	};
}, false);