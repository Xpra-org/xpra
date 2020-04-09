/**
MIT License

Copyright (c) 2019 Mark Harkin, 2016 Dylan Hicks (aka. dylanh333)

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


(function(){
    function $(selector, context){
        context = context || document;
        return context["querySelectorAll"](selector);
    }

    function forEach(collection, iterator){
        for(const key in Object.keys(collection)){
            iterator(collection[key]);
        }
    }

    function showMenu(){
        const menu = this;
        const ul = $("ul", menu)[0];
        //hack to hide the menu from javascript
        if(!ul){
			return;
		}

        if(ul.classList.contains("-hide")){
			ul.classList.remove("-hide");
			ul.parentElement.classList.remove("-active");
			return;
		}

        if(ul.classList.contains("-visible")){
			return;
		}

        menu.classList.add("-active");
        ul.classList.add("-animating");
        ul.classList.add("-visible");
        setTimeout(function(){
            ul.classList.remove("-animating");
        }, 25);
    }

    function hideMenu(){
        const menu = this;
        const ul = $("ul", menu)[0];

        if(!ul || !ul.classList.contains("-visible")) return;

        menu.classList.remove("-active");
        ul.classList.add("-animating");
        setTimeout(function(){
            ul.classList.remove("-visible");
            ul.classList.remove("-animating");
        }, 300);
    }

    function hideAllInactiveMenus(){
        const menu = this;
        forEach(
            $("li.-hasSubmenu.-active:not(:hover)", menu.parent),
            function(e){
                e.hideMenu && e.hideMenu();
            }
        );
    }

    function hideAllMenus(){
        const menu = this;
        forEach(
            $("li.-hasSubmenu", menu.parent),
            function(e){
                e.hideMenu && e.hideMenu();
            }
        );
    }

    window.addEventListener("load", function(){
        forEach($(".Menu li.-hasSubmenu"), function(e){
            e.showMenu = showMenu;
            e.hideMenu = hideMenu;
        });

        forEach($(".Menu > li.-hasSubmenu"), function(e){
            e.addEventListener("click", showMenu);
        });

        forEach($(".Menu > li.-hasSubmenu li"), function(e){
            e.addEventListener("mouseenter", hideAllInactiveMenus);
        });

        forEach($(".Menu > li.-hasSubmenu li.-hasSubmenu"), function(e){
            e.addEventListener("mouseenter", showMenu);
        });

        forEach($("a"), function(e){
            e.addEventListener("click", hideAllMenus);
        });

        document.addEventListener("click", hideAllInactiveMenus);
    });
})();
