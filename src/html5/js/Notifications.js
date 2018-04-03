/*
 * This file is part of Xpra.
 * Copyright (C) 2016-2018 Antoine Martin <antoine@devloop.org.uk>
 * Copyright (c) 2016 Spikes, Inc.
 * Licensed under MPL 2.0, see:
 * http://www.mozilla.org/MPL/2.0/
 *
 */

$(function() {

	window.doNotification = function(type, nid, title, message, timeout, icon, actions, hints, onAction, onClose){
		console.debug("doNotification", type, nid, title, message, timeout, icon, actions, hints, onAction, onClose);
		var nID = 'notification' + nid;
		var a = $('<div id="' + nID + '" class="alert ' + type + '">'+
					'<img class="notification_icon" id="notification_icon' + nID + '"></img>'+
					'<span class="title">'+title+'</span>'+
					'<span class="message">' + message + '</span>'+
					'<div class="dismiss">&#215;</div>'+
				  '</div>');
		$('.notifications').prepend(a);
		if (actions) {
			var notification_buttons = $('<div class="notification_buttons"></div>');
			a.append(notification_buttons);
			for (var i = 0; i < actions.length; i+=2) {
				var action_id = actions[i];
				var action_label = actions[i+1];
				var notification_button = window._notification_button(nid, action_id, action_label, onAction, onClose);
				notification_buttons.append(notification_button);
			}
		}
		$('.notifications').prepend(a);
		if (icon) {
			var encoding = icon[0],
				//w = icon[1],
				//h = icon[2],
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
					if (onClose) {
						onClose(nid, 3, "user clicked dismiss");
					}
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
					a.find('.dismiss').trigger('click');
					if (onClose) {
						onClose(nid, 1, "timeout");
					}
				} else {
					a.find('sec').text(tleft);
					a.data('timeLeft', tleft);
				}
			}, 1000);
		}
		return a;
	};

	window._notification_button = function(nid, action_id, action_label, onAction, onClose) {
		var notification_button = $('<div class="notification_button" id=notification"'+action_id+'">'+action_label+'</div>');
		notification_button.on("click", function() {
			window.closeNotification(nid);
			if (onAction) {
				onAction(nid, action_id);
			}
			if (onClose) {
				onClose(nid, 3, "user clicked action");
			}
		});
		return notification_button;
	}
	

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