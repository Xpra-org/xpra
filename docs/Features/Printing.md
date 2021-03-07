# ![Printer](https://xpra.org/icons/printer.png) Printing

This feature allows printers connected to the client to show as virtual printers on the server so that printing can transparently be forwarded back to the client's printer(s).

This functionality shares most of the code with the [file transfers](./FileTransfers.md), as the print job is first rendered to a file before being sent to the client.

## Installation and platform support
* MS Windows and MacOS clients should work out of the box
* [CentOS](https://www.centos.org/) requires manual setup to support MacOS clients as the [cups-pdf](http://www.cups-pdf.de/) package is not available in the default repositories
* Debian and Ubuntu: the dependencies are listed as "suggestions" only, so you may need to run `apt-get install cups-filters cups-common cups-pdf python3-cups` to install the missing pieces
* you may encounter some permission issues: the user running the xpra server must be a printer administrator - whatever group that may be (if you need to add your user to a group you will also then need to logout and login again to gain the new privileges):
    * for Fedora and centos the `sys` group: `gpasswd -a $USER sys`
    * for Debian and Ubuntu the `lpadmin` group: `usermod -a -G lpadmin $USER`
* the cups backend installed must have `0700` permissions: `chmod 700 /usr/lib/cups/backend/xpraforwarder`
* [SELinux](https://en.wikipedia.org/wiki/Security-Enhanced_Linux) can cause problems: either disable it or use the "cups_xpra" policy add-on (see [#815](../https://github.com/Xpra-org/xpra/issues/815)
* forwarding is only supported to a Posix server, support for MS Windows and MacOS _servers_ may be added in the future
* do not use socket authentication on your local sockets (see [#1286](../https://github.com/Xpra-org/xpra/issues/1286)
* MacOS clients use Postscript [#995](../https://github.com/Xpra-org/xpra/issues/995), other clients use PDF for transport
* MacOS [shadow server](./ShadowServer) Support starting with version `10.10` (aka Yosemite) prevents the xpra cups backend from connecting to the xpra server, to fix this run: `sudo sh -c 'echo "Sandboxing Relaxed" >> /etc/cups/cups-files.conf';sudo launchctl stop org.cups.cupsd`


## Implementation

_How does this work?_
The xpra client exports the list of local printers to the xpra server, the server can then create the same list of virtual printers using the `lpadmin` command.\
Those virtual printers are actually PDF or postscript scripts.\
When the user sends a print job to one of those virtual printers, the script captures the rendered document and forwards it to the client who owns this particular virtual printer.
The xpra client then sends this PDF / postscript document straight to the actual printer.

The HTML5 client is written in Javascript so it does not have access to the printer device information and the PDF document is presented for printing via the standard browser's print dialog.


## Debugging
* run the [printing.py](../../xpra/platform/printing.py) diagnostic script to see which printers are detected - this script is available as `Print.exe` on MS Windows and as `Xpra.app/Contents/Helpers/Print` on MacOS
* you can use the same script to print files, ie: `./xpra/platform/printing.py /path/to/yourfile.pdf`
* run the client and server with the `-d printing` debug flags (see [debug logging](./Logging))
* look for the cups backend messages in your system log (ie: with journald: `sudo journalctl -f -t xpraforwarder`)
* for debugging the cups server backend, run: `cupsctl --debug-logging`


## Related Issues
* [#1344](https://github.com/Xpra-org/xpra/issues/1344) better printer options handling and forwarding
* [#1228](https://github.com/Xpra-org/xpra/issues/1228) printing enhancements: cups backend status
* [#1286](https://github.com/Xpra-org/xpra/issues/1286) printing conflicts with socket authentication module 'env'
* [#964](https://github.com/Xpra-org/xpra/issues/964) printer forwarding doesn't work with encryption or authentication
* [#928](https://github.com/Xpra-org/xpra/issues/928) printer forwarding on ubuntu
