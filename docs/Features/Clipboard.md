![Clipboard](https://xpra.org/icons/clipboard.png)

This feature allows you to copy from outside the xpra session and paste inside it, and vice versa.
For various reasons, this doesn't always work quite as well as expected - see below for more details.


## Platform specific issues:
* Mac OSX and MS Windows clients only have a single clipboard selection whereas X11 has three: `CLIPBOARD`, `PRIMARY` and `SECONDARY`; therefore we need to choose which one to exchange with: see `local-clipboard` and `remote-clipboard` switches
* on MS Windows, the OS requests the clipboard data as soon as we claim ownership
* on MacOS, we have to use polling to see client-side changes
* the HTML5 client can only access the clipboard when the browser decides it is appropriate to do so: usually following clicks or specific key combinations, it may also request permission once and this cannot be easily enabled afterwards once it has been denied
* Wayland severely restricts access to the clipboard, making it impossible to synchronize it properly

## Configuration Options
* `clipboard-direction`: can be used to restrict the direction of the clipboard data transfers. This setting is also available from the system tray menu.
* `clipboard-filter-file`: can be used to filter out clipboard contents using a file containing regular expressions
* `local-clipboard` / `remote-clipboard`: can be used to select which clipboard selection to synchronize with


## Technical Constraints
Clipboard support is an ongoing struggle.

You must ensure that there are no other clipboard synchronization tools already running as those are very likely to interfere and cause synchronization loops, wasted bandwidth, trigger application bugs, etc

In particular, avoid using the clipboard synchronization from your virtualization solution if you use one (ie: virtualbox, vmware, etc), or from tools like synergy. Alternatively, you can disable xpra's clipboard instead. Just avoid running both at the same time.


## Testing and debugging the clipboard
There is a debugging tool which can be launched using `xpra clipboard-test`.

The easiest way to test the clipboard on X11 platforms is to use `xclip` tool to set and verify the contents of each clipboard.
* to set the "primary" clipboard contents to the string "_primary_":\
    `echo _primary_ | xclip -i -selection primary`
* To print the contents of the "primary" clipboard:\
    `xclip -o -selection primary`

Note: on win32, you will need to change the clipboard currently in use to match the one you modify, this must be done before changing the value to ensure it is propagated.

### Debugging
just add `-d clipboard` to your xpra command line.


## Useful Pointers
* [How does X11 clipboard handle multiple data formats?](http://stackoverflow.com/questions/3571179/how-does-x11-clipboard-handle-multiple-data-formats)
* [x11-clipboard.cpp](http://www.virtualbox.org/svn/vbox/trunk/src/VBox/GuestHost/SharedClipboard/x11-clipboard.cpp) from `VirtualBox`
* [operating system specific clipboards](http://en.wikipedia.org/wiki/Clipboard_(computing)#Operating_system-specific_clipboards) on wikipedia
* [The X11 clipboard](http://pvanhoof.be/files/Problems%20of%20the%20X11%20clipboard.pdf) _An overview of it's problems and a proposed solution_
And here is a good quote from it:
  _Clipboard sharing and network transparency: It's nearly impossible to make the clipboard shared across different desktop computers. In fact it is possible, but such an implementation would be needlessly difficult and complex. The same can be said 
of support for virtualization (Qemu, Xen, VMWare). Sharing the clipboard between a virtual machine and the desktop itself is painfully difficult to implement correctly (in case X11 is running on the host operating system)._
}}}


## Source code
[xpra/clipboard](../xpra/tree/master/xpra/clipboard/)


## Related tickets
* [#2312](https://github.com/Xpra-org/xpra/issues/2312) clipboard images with html5 client
* [#2634](https://github.com/Xpra-org/xpra/issues/2634) disable clipboard watermarks
* [#1844](https://github.com/Xpra-org/xpra/issues/1844) async clipboard api
* [#41](https://github.com/Xpra-org/xpra/issues/41): when we support concurrent users on the same session, we currently give the clipboard to the first client - doing anything else will be quite tricky
* [#812](https://github.com/Xpra-org/xpra/issues/812) re-implement clipboard without gtk or nested main
* [#1167](https://github.com/Xpra-org/xpra/issues/1167) tray menu clipboard choice irreversible
* [#1139](https://github.com/Xpra-org/xpra/issues/1139) XPRA - Matlab - Clipboard blinking, UI unresponsive
* [#966](https://github.com/Xpra-org/xpra/issues/966) provide a persistent setting to select the default clipboard to synchronize
* [#1112](https://github.com/Xpra-org/xpra/issues/1112) clipboard notification flashing constantly
* [#1018](https://github.com/Xpra-org/xpra/issues/1018) recursion depth error
* [#883](https://github.com/Xpra-org/xpra/issues/883) Pasting into WYSIWYG editors rich text fails and causes too many clipboard requests
* [#842](https://github.com/Xpra-org/xpra/issues/842) html5 client clipboard support
* [#834](https://github.com/Xpra-org/xpra/issues/834) Sync issue with win32 client clipboard
* [#823](https://github.com/Xpra-org/xpra/issues/823) Session hangs and dies
* [#877](https://github.com/Xpra-org/xpra/issues/877) clipboard hitting maximum requests per second limit
* [#735](https://github.com/Xpra-org/xpra/issues/735) Clipboard working incorrect with java-applications (x2go + xpra)
* [#703](https://github.com/Xpra-org/xpra/issues/703) Copying URL from web browser address bar on remote host fails
* [#272](https://github.com/Xpra-org/xpra/issues/272) win32 multiple clipboards enhancement
* [#318](https://github.com/Xpra-org/xpra/issues/318) osx client-to-server clipboard support
* [#273](https://github.com/Xpra-org/xpra/issues/273) handle more clipboard formats
* [#274](https://github.com/Xpra-org/xpra/issues/274) advanced clipboard filtering
* [#275](https://github.com/Xpra-org/xpra/issues/275) handle clipboard large data transfers better
* [#276](https://github.com/Xpra-org/xpra/issues/276) limit clipboard direction
* [#452](https://github.com/Xpra-org/xpra/issues/452) detect and avoid creating clipboard loops
* [#313](https://github.com/Xpra-org/xpra/issues/313) speedup paste
* [#184](https://github.com/Xpra-org/xpra/issues/184) clipboard related bug, clipboard can fire at any time... so bugs may appear to come from somewhere else when in fact it is the clipboard that is the source of the problem - to keep in mind
* [#162](https://github.com/Xpra-org/xpra/issues/162) very hard to reproduce bug - relied on the list (and their order) of X11 atoms defined, as we tried to parse invalid values as X11 atoms
* [#176](https://github.com/Xpra-org/xpra/issues/176) 32-bit vs 64-bit structures issue
* [#156](https://github.com/Xpra-org/xpra/issues/156) we drop clipboard packets that are too big - rather than causing network problems (bug was that we dropped the connection instead - oops!)
* [#52](https://github.com/Xpra-org/xpra/issues/52) another atom name issue, this time with Java apps
* [#8](https://github.com/Xpra-org/xpra/issues/8), [#84](https://github.com/Xpra-org/xpra/issues/84) and [#99](https://github.com/Xpra-org/xpra/issues/99) (dupe: [#104](https://github.com/Xpra-org/xpra/issues/104)): more clipboard atom problems
* [#11](https://github.com/Xpra-org/xpra/issues/11) win32 and osx clipboard ticket (old)
