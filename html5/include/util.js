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