/**
 * Utility functions.
 *
 */


/**
 * Adds window.location.getParameter to those browsers that don't have it:
 *
 * See:
 * http://stackoverflow.com/a/8812157/428751
 */
if (!window.location.getParameter ) {
	window.location.getParameter = function(key) {
		function parseParams() {
				var params = {},
						e,
						a = /\+/g,	// Regex for replacing addition symbol with a space
						r = /([^&=]+)=?([^&]*)/g,
						d = function (s) { return decodeURIComponent(s.replace(a, " ")); },
						q = window.location.search.substring(1);

				while (e = r.exec(q))
						params[d(e[1])] = d(e[2]);

				return params;
		}

		if (!this.queryStringParams)
				this.queryStringParams = parseParams();

		return this.queryStringParams[key];
	};
}


function in_array(needle, haystack){
	"use strict";
    var found = 0;
    for (var i=0, len=haystack.length;i<len;i++) {
        if (haystack[i] == needle) return i;
            found++;
    }
    return -1;
}

function get_bool(v, default_value) {
	"use strict";
	//show("get_bool("+v+", "+default_value+")");
	if (in_array(v, ["true", "on", true])>=0)
		return true;
	if (in_array(v, ["false", false])>=0)
		return false;
	return default_value;
}

function parse_port(s) {
	"use strict";
	try {
		for (var i=0; i<s.length; i++) {
			if ("0123456789".indexOf(s.charAt(i))<0) {
				set_ui_message("invalid port", "red");
				return 0;
			}
		}
		return parseInt(s);
	}
	catch (e) {
		set_ui_message("invalid port", "red");
		return 0;
	}
}

var ValidIpAddressRegex = /^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$/;
var ValidHostnameRegex = /^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$/;
function parse_host(s) {
	"use strict";
	if (s==null || s.length==0)
		return "";
	if (s.match(ValidIpAddressRegex) || s.match(ValidHostnameRegex))
		return s;
	set_ui_message("invalid host string", "red");
	return "";
}



function get_keyboard_layout() {
	"use strict";
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


function guess_platform_processor() {
	"use strict";
	//mozilla property:
	if (navigator.oscpu)
		return navigator.oscpu;
	//ie:
	if (navigator.cpuClass)
		return navigator.cpuClass;
	return "unknown";
}

function guess_platform_name() {
	"use strict";
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

function guess_platform() {
	"use strict";
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
