/*
 * This file is part of Xpra.
 * Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2016 Spikes, Inc.
 * Licensed under MPL 2.0, see:
 * http://www.mozilla.org/MPL/2.0/
 *
 */

$(function() {

	window.doNotification = function(type, nid, title, message, timeout, icon, onTimeOut){
		var nID = 'notification' + nid;
		var a = $('<div id="' + nID + '" class="alert ' + type + '">'+
					'<img class="notification_icon" id="notification_icon' + nID + '"></img>'+
					'<span class="title">'+title+'</span>'+
					'<span class="message">' + message + '</span>'+
					'<div class="dismiss">&#215;</div>'+
				  '</div>');
		$('.notifications').prepend(a);
		if (icon) {
			var encoding = icon[0],
				w = icon[1],
				h = icon[2],
				img_data = icon[3];
			if (encoding=="png") {
				var src = "data:image/"+encoding+";base64," + window.btoa(img_data);
				$("#notification_icon"+nID).attr('src', src);
			}
		}
		
		a.on('click', '.dismiss', function() {
			a.removeClass('visible').addClass('hidden');
			a.on('transitionend webkitTransitionEnd', $.debounce(250, function() {
					a.trigger('dismissed');
					a.remove();
			}));
		});

		setTimeout(function(){
				a.addClass('visible');
		}, 1);

		if(timeout){
			a.data('timeLeft', timeout);
			var it = setInterval(function() {
				var tleft = a.data('timeLeft') - 1;
				if (a.data('timeLeft') === 0) {
					if (onTimeOut) {
						onTimeOut(a);
					} else {
						a.find('.dismiss').trigger('click');
					}
				} else {
					a.find('sec').text(tleft);
					a.data('timeLeft', tleft);
				}
			}, 1000);
		}
		return a;
	};

	window.closeNotification = function(nid) {
		var nID = 'notification' + nid;
		$('.notifications').find('#'+nID).find('.dismiss').trigger('click');
	}

	window.clearNotifications = function(){
		$('.notifications').find('.dismiss').trigger('click');
	};

	window.removeNotifications = function(){
		$('.notifications').empty();
	};
});