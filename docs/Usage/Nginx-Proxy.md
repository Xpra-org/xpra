# Nginx Proxy

Instead of using xpra's builtin [proxy server](Proxy-Server.md), the [apache http server](https://httpd.apache.org/) can be configured as a single point of entry, on a single port. \
Just like xpra's proxy, the apache proxy can provide multiple sessions, potentially on multiple remote backend servers.

This works well with both the [html5 client](https://github.com/Xpra-org/xpra-html5) and the regular xpra client with `ws://` and `wss://` URLs.


## SSL

In these examples, it may be useful to have [SSL](../Network/SSL.md) certificates ready to use. \
Having [mkcert](https://mkcert.org/) installed can help to ensure that the certificates generated are trusted locally. \
If your package manager did not create any certificates when you installed the xpra server, you can do so now:
```shell
sudo /usr/bin/xpra setup-ssl
```
This command will not overwrite any existing certificates.

---

## Basic Configuration

<details>
  <summary>show</summary>

### Create the config
```shell
cat > /usr/share/nginx/xpra-basic.conf << EOF
events {
}

http {

	map $http_upgrade $connection_upgrade {
		default upgrade;
		''	  close;
	}

	server {
		listen 443 ssl;
		listen 80;

		root /usr/share/xpra/www;

		ssl_certificate /etc/xpra/ssl/ssl-cert.pem;
		ssl_certificate_key /etc/xpra/ssl/key.pem;

		location / {
			proxy_pass http://127.0.0.1:10000;

			proxy_http_version 1.1;
			proxy_buffering off;
			proxy_cache_bypass $http_upgrade;
			proxy_set_header Upgrade $http_upgrade;
			proxy_set_header Connection "Upgrade";
			proxy_set_header Host $host;
		}
	}
}
EOF
```
### Start nginx:
```shell
sudo nginx -c xpra-basic.conf
```

### Xpra server
Start an xpra server on port 10000:
```shell
xpra start --bind-tcp=0.0.0.0:10000 --start=xterm
```
(beware: [authentication](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Authentication.md) is turned off for simplicity)

Then you can simply open your browser to connect to the session via the nginx proxy:
```shell
xdg-open http://localhost/
```
Or even via https if the certificates are configured correctly:
```shell
xdg-open https://localhost/
```
</details>


---


## Multiple Servers

<details>
  <summary>show</summary>

This example configuration maps different URLs to servers on different ports.

```
http {

	map $http_upgrade $connection_upgrade {
		default upgrade;
		''	  close;
	}

	server {
		listen 443 ssl;
		listen 80;

		root /usr/share/xpra/www;

		ssl_certificate /etc/xpra/ssl/ssl-cert.pem;
		ssl_certificate_key /etc/xpra/ssl/key.pem;

		proxy_redirect off;
		proxy_http_version 1.1;
		proxy_buffering off;
		proxy_cache_bypass $http_upgrade;
		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "Upgrade";
		proxy_set_header Host $host;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;

		location /xpra1 {
			rewrite /xpra1/(.*) /$1 break;
			proxy_pass http://127.0.0.1:10000;
		}
		location /xpra2 {
			rewrite /xpra2/(.*) /$1 break;
			proxy_pass http://127.0.0.1:10001;
		}
	}
}
```
</details>


## Advanced Options

<details>
  <summary>show</summary>

Most of the options below can make the connection more robust
and should be applied to the `location` matching the xpra server being proxied for. \
However, increasing the timeouts should not be necessary as the xpra protocol
already includes its own ping packets every few seconds,
which should ensure that the connection is kept alive.

These options may even introduce new issues,
by making it harder for nginx to detect broken connections.

| Option	                                                                                                   | Recommended value                      | Purpose                                                                                                               |
|--------------------------------------------------------------------------------------------------------------|----------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`proxy_connect_timeout`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_connect_timeout)   | unchanged                              | a lower value can be used to fail faster when xpra servers are already started and initial connections should be fast |
| [`proxy_read_timeout`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_read_timeout)         | 10d                                    | or more, increase this option to prevent unexpected disconnections                                                    |
| [`proxy_send_timeout`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_send_timeout)         | 10d                                    | same as `proxy_read_timeout`                                                                                          |
| [`limit_except`](https://nginx.org/en/docs/http/ngx_http_core_module.html#limit_except)                      | `limit_except GET POST { deny  all; }` | prevent unwanted http requests from reaching xpra's http server                                                       |
| [`proxy_socket_keepalive`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_socket_keepalive) | unchanged                              | should not be needed, can be enabled                                                                                  |
| [`tcp_nodelay`](https://nginx.org/en/docs/http/ngx_http_core_module.html#tcp_nodelay)                        | on                                     | keep the latency low, this should already be enabled automatically for WebSocket connections                          |
| [`tcp_nopush`](https://nginx.org/en/docs/http/ngx_http_core_module.html#tcp_nopush)                          | off                                    | may introduce unwanted latency                                                                                        |
| [`proxy_no_cache`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_no_cache)                 | `1`                                    | prevent caching of the xpra-html5 client                                                                              |
| [`proxy_cache_bypass`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache_bypass)         | `1`                                    | prevent caching of the xpra-html5 client                                                                              |

The following options should not need to be modified:
* [`client_max_body_size`](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size) - [does not affect WebSocket connections](https://serverfault.com/questions/1034906/) and all the xpra clients use chunked transfers anyway - as for the xpra-html5 client itself, it is orders of magnitude smaller than the default limit
* [`proxy_intercept_errors`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_intercept_errors) - once a WebSocket connection is established, http error codes are not used
* [`keepalive_timeout`](https://nginx.org/en/docs/http/ngx_http_core_module.html#keepalive_timeout) - see `proxy_socket_keepalive` above
* [`send_timeout`](https://nginx.org/en/docs/http/ngx_http_core_module.html#send_timeout) - see `proxy_send_timeout` above
* [`proxy_buffering`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering) - should not affect WebSocket connections
* [`proxy_buffering`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering) [`proxy_request_buffering`](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering) - let nginx handle http requests, this does not affect connections upgraded to WebSocket

</details>