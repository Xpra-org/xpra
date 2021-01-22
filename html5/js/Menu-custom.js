/**
MIT License

Copyright (c) 2019 Mark Harkin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

*/

function addWindowListItem(wid, title){
	const li = document.createElement("li");
	li.className="windowlist-li";
	li.id = "windowlistitem"+wid;

	const a = document.createElement("a");

	a.id = "windowlistitemlink"+wid;

	a.onmouseover=function(e){
		if (e.ctrlKey) {
			client._window_set_focus(client.id_to_window[wid]);
		}
	};
	a.onclick=function(){
		if(jQuery(client.id_to_window[wid].div).is(":hidden")){
			jQuery(client.id_to_window[wid].div).show();
		}
		this.parentElement.parentElement.className="-hide";
		client._window_set_focus(client.id_to_window[wid]);
	};

	const divLeft = document.createElement("div");
	divLeft.id="windowlistdivleft"+wid;
	divLeft.className="menu-divleft";
	const img = new Image();
	img.id = "windowlistitemicon"+wid;
	img.src="/favicon.png";
	img.className="menu-content-left";
	divLeft.appendChild(img);

	const titleDiv = document.createElement("div");
	titleDiv.appendChild(document.createTextNode(title));
	titleDiv.id = "windowlistitemtitle"+wid;
	titleDiv.className="menu-content-left";
	divLeft.appendChild(titleDiv);

	const divRight = document.createElement("div");
	divRight.className="menu-divright";

	const img2 = new Image();
	img2.id = "windowlistitemclose"+wid;
	img2.src="icons/close.png";
	img2.title="Close";
	img2.className="menu-content-right";
	img2.onclick=function(){ client._window_closed(client.id_to_window[wid]); };
	const img3 = new Image();
	img3.id = "windowlistitemmax"+wid;
	img3.src="icons/maximize.png";
	img3.title="Maximize";
	img3.onclick=function(){ client.id_to_window[wid].toggle_maximized(); };
	img3.className="menu-content-right";
	const img4 = new Image();
	img4.id = "windowlistitemmin"+wid;
	img4.src="icons/minimize.png";
	img4.title="Minimize";
	img4.onclick=function(){ client.id_to_window[wid].toggle_minimized(); };
	img4.className="menu-content-right";

	divRight.appendChild(img2);
	divRight.appendChild(img3);
	divRight.appendChild(img4);
	a.appendChild(divLeft);
	a.appendChild(divRight);
	li.appendChild(a);

	document.getElementById("open_windows_list").appendChild(li);
}

function removeWindowListItem(itemId){
	const element = document.getElementById("windowlistitem" + itemId);
	if(element && element.parentNode){
		element.parentNode.removeChild(element);
	}
}

$(function() {
	const float_menu = $("#float_menu");
	float_menu.draggable({
		cancel: '.noDrag',
		containment: 'window',
		scroll: false
	});
	float_menu.on("dragstart",function(ev,ui){
		client.mouse_grabbed = true;
		//set_focus_cb(0);
	});
	float_menu.on("dragstop",function(ev,ui){
		client.mouse_grabbed = false;
		client.reconfigure_all_trays();
	});

});

