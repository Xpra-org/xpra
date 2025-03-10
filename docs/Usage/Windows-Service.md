# Windows System Service

This service is only included in full builds.


The [`Xpra-Service.cpp`](https://github.com/Xpra-org/xpra/blob/master/packaging/MSWindows/service/Xpra-Service.cpp)
is compiled into `Xpra-Service.exe` using `vscode` or just via `msbuild` during the build.

This service can be installed by running `./Xpra-Service.exe install`,
then it can be managed from the GUI `services.msc` tool.
It is not configured to start automatically. \
Use `./Xpra-Service.exe uninstall` to unregister it.

The xpra `.exe` installer should have created the registry key `HKLM\Software\Xpra\InstallPath`,
typically pointing to `C:\Program Files\Xpra`.

The `start` action for this service will run `Xpra-Proxy.exe start` from this `InstallPath`.

The `Xpra-Proxy.exe` scripts is a simple delegation wrapper ([source](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/scripts/proxy.py))
packaged as a GUI application which just calls
[`xpra.platform.win32.service`](https://github.com/Xpra-org/xpra/blob/master/xpra/platform/win32/service.py).

This service just starts an xpra proxy server using the hard-coded arguments:
```shell
Xpra proxy --bind-tcp=0.0.0.0:14500,auth=sys,client-username=true,verify-username=true
```

The proxy will log to a file.
The exact path of this log file can be obtained by querying the proxy server:
```shell
Xpra_cmd info tcp://localhost:14500/ | grep log-file
```
Normally, it should be `C:\Windows\System32\config\systemprofile\AppData\Local\Xpra\System-Proxy.log`

---

Work in progress: it isn't entirely clear which API the proxy
is meant to use to start a new session, station and desktop once users
have authenticated.
At time of writing, the proxy server can only mediate for existing sessions,
and only for `Administrators`.
