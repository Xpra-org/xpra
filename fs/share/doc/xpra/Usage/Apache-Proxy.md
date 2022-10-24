# Apache Proxy

Instead of using xpra's builtin [proxy server](./Proxy-Server.md), the [apache http server](https://httpd.apache.org/) can be configured as a single point of entry, on a single port.  
Just like xpra's proxy, the apache proxy can provide multiple sessions, potentially on multiple remote backend servers.

This works well with both the [html5 client](https://github.com/Xpra-org/xpra-html5) and the regular xpra client.

## Example Configuration
```shell
cat > /etc/httpd/conf.modules.d/20-proxy.conf << EOF
<Location "/xpra1">
  RewriteEngine on
  RewriteCond %{HTTP:UPGRADE} ^WebSocket$ [NC]
  RewriteCond %{HTTP:CONNECTION} ^Upgrade$ [NC]
  RewriteRule .* ws://localhost:20001/%{REQUEST_URI} [P]
  ProxyPass ws://localhost:20001
  ProxyPassReverse ws://localhost:20001
</Location>

<Location "/xpra2">
  RewriteEngine on
  RewriteCond %{HTTP:UPGRADE} ^WebSocket$ [NC]
  RewriteCond %{HTTP:CONNECTION} ^Upgrade$ [NC]
  RewriteRule .* ws://localhost:20002/%{REQUEST_URI} [P]
  ProxyPass ws://localhost:20002
  ProxyPassReverse ws://localhost:20002
</Location>
EOF
```

## Usage
Start the xpra servers defined in the apache configuration above:
```shell
xpra start --bind-tcp=0.0.0.0:20001 --start=xterm
xpra start --bind-tcp=0.0.0.0:20002 --start=xterm
```
(beware: [authentication](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Authentication.md) is turned off for simplicity)

Then you can simply open your browser at these locations (`/xpra1` and `/xpra2` in the example config):
```shell
xdg-open http://localhost/xpra1/foo
```

Or using the regular command line client using a websocket connection:
```shell
xpra attach ws://localhost/xpra1/foo
xpra attach ws://localhost/xpra1/bar
```
