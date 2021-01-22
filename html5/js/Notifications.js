/*
 * This file is part of Xpra.
 * Copyright (C) 2016-2018 Antoine Martin <antoine@xpra.org>
 * Copyright (c) 2016 Spikes, Inc.
 * Licensed under MPL 2.0, see:
 * http://www.mozilla.org/MPL/2.0/
 *
 */

$(function() {

	window.notification_timers = {};

	window.doNotification = function(type, nid, title, message, timeout, icon, actions, hints, onAction, onClose){
		console.debug("doNotification", type, nid, title, message, timeout, icon, actions, hints, onAction, onClose);
		const nID = 'notification' + nid;
		const a = $('<div id="' + nID + '" class="alert ' + type + '">'+
					'<img class="notification_icon" id="notification_icon' + nID + '">'+
					'<span class="title">'+title+'</span>'+
					'<span class="message">' + message + '</span>'+
					'<div class="dismiss">&#215;</div>'+
				  '</div>');
		const notifications_elements = $('.notifications');
		notifications_elements.prepend(a);
		if (actions) {
			const notification_buttons = $('<div class="notification_buttons"></div>');
			a.append(notification_buttons);
			for (let i = 0; i < actions.length; i+=2) {
				const action_id = actions[i];
				const action_label = actions[i+1];
				const notification_button = window._notification_button(nid, action_id, action_label, onAction, onClose);
				notification_buttons.append(notification_button);
			}
		}
		notifications_elements.prepend(a);
		if (icon) {
			const encoding = icon[0],
				//w = icon[1],
				//h = icon[2],
				img_data = icon[3];
			if (encoding=="png") {
				const src = "data:image/"+encoding+";base64," + window.btoa(img_data);
				$("#notification_icon"+nID).attr('src', src);
			}
		}

		a.on('click', '.dismiss', function() {
			window.cancelNotificationTimer(nid);
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
			window.notification_timers[nid] = setInterval(function() {
				const tleft = a.data('timeLeft')-1;
				if (a.data('timeLeft')===0) {
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
		const notification_button = $('<div class="notification_button" id=notification"'+action_id+'">'+action_label+'</div>');
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
	};

	window.cancelNotificationTimer = function(nid) {
		const timer = window.notification_timers[nid];
		if (timer) {
			window.clearInterval(timer);
			delete window.notification_timers[nid];
		}
	};
	window.cancelNotificationTimers = function() {
		for (const nid in window.notification_timers) {
			window.cancelNotificationTimer(nid);
		}
	};

	window.closeNotification = function(nid) {
		window.cancelNotificationTimer(nid);
		const nID = 'notification' + nid;
		$('.notifications').find('#'+nID).find('.dismiss').trigger('click');
	};

	window.clearNotifications = function(){
		window.cancelNotificationTimers();
		$('.notifications').find('.dismiss').trigger('click');
	};

	window.removeNotifications = function(){
		window.cancelNotificationTimers();
		$('.notifications').empty();
	};
});