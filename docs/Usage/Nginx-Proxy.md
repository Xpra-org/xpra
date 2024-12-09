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
xdg-open http://localhost/
```
</details>
