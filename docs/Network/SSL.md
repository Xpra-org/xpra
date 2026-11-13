# SSL

SSL is the colloquial term which refers to both `SSL` and `TLS` socket encryption.

<div class="docs-section-heading" markdown="1">

## Basic example

</div>

For step-by-step instructions, expand this:
<details markdown="1">
  <summary>Basic Example</summary>

start a server with TCP and SSL support using an existing certificate `cert.pem` (see below for generating one):
```
xpra seamless --start=xterm \
     --bind-tcp=0.0.0.0:10000 \
     --ssl-cert=/path/to/cert.pem \
     --ssl-key=/path/to/key.pem
```
connect a client:
```
xpra attach ssl://127.0.0.1:10000/
```
To avoid this error when the server uses a self-signed certificate:
```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate
```
You can:
* *temporarily* add `--ssl-server-verify-mode=none` to your client command line
* or copy the certificate to the client then use `ssl-ca-certs` to use it for validation:
```
   xpra attach ssl://host:10000/ --ssl-ca-certs=./cert.pem
```

### Generating a self-signed certificate
```
openssl req -new -x509 -days 365 -nodes -out cert.pem -keyout key.pem -sha256
```
For trusting your own certificates and testing with localhost, see [certificates for localhost](https://letsencrypt.org/docs/certificates-for-localhost/)
</details>

***

<div class="docs-section-heading" markdown="1">

## Socket upgrades

</div>
Once a server is configured for `SSL` - usually by adding the `--ssl-cert` option, its TCP sockets (`bind-tcp` option) can automatically be upgraded to:
* `ssl`, obviously
* `http` and `ws` (`websockets`) connections can be upgraded to `https` and `wss` (`secure websockets`)

The same way, any `ws` sockets specified with the `bind-ws` option can then be upgraded to `wss`.

This allows a single port to be used with multiple protocols (including also [SSH](SSH.md)), which can more easily go through some firewalls and may be required by some network policies. Client certificates can also be used for authentication.

Each type of upgrade can be turned off individually with its own option:
on the server, `ssl-upgrade` is enabled whenever SSL is configured (unless `ssl=no`),
`websocket-upgrade` and `ssh-upgrade` are enabled by default,
`rfb-upgrade` is a delay in seconds (`5` by default, `0` to disable)
and `rdp-upgrade` is disabled by default.

### Negotiated TLS upgrades

A native Xpra client can also start with a plain TCP connection and allow the
server to request a TLS upgrade before authentication. Enable this on the Python
client with:

```shell
xpra attach tcp://127.0.0.1:10000/ --ssl-upgrade=yes
```

The client advertises the top-level `ssl-upgrade: true` capability in its `hello`.
The server can then offer an upgrade if it has a TLS certificate, SSL upgrades
are enabled for the connection, and the client did not request AES encryption.
The client acknowledges the offer, performs a TLS handshake on the same socket,
and sends its `hello` again over TLS. See the
[protocol](Protocol.md#53-authentication-and-upgrade-packets) for the packet exchange.

The Python client only advertises this capability when SSL upgrade support is
enabled. Omitting it or setting it to false prevents the server from offering
this upgrade. `--ssl-upgrade=yes` permits an upgrade; the connection stays plain
TCP if the server does not offer one.

Negotiated upgrades are opportunistic: the Python client does not verify the
server's certificate or hostname by default. For verified TLS from the start,
use an `ssl://` URL and configure certificate trust as described above.

<div class="docs-section-heading" markdown="1">

## SSL options

</div>
There are many options to configure and certificates to deal with.
See https://docs.python.org/3/library/ssl.html, on which this is based.

For more details see [#1252](https://github.com/Xpra-org/xpra/issues/1252).

<div class="docs-section-heading" markdown="1">

## Default certificate

</div>
When using the binary packages from https://xpra.org, a self-signed SSL certificate will be generated during the first installation.\
It is placed in:
* `/etc/xpra/ssl/` on Posix platforms
* `C:\ProgramData\Xpra\ssl\` on MS Windows
* `/Library/Application Support/Xpra/ssl/` on Mac OS

That directory holds the private key as `key.pem` and the certificate as
`cert.pem`. Xpra uses these separate files by default. Configure them explicitly
with `--ssl-key` and `--ssl-cert` when using certificates stored elsewhere.

Older installations may also contain a combined `ssl-cert.pem`. Explicitly
configured combined files remain supported, but separate certificate and key
files prevent private key material from being handled where only the public
certificate is needed.

<div class="docs-section-heading" markdown="1">

## Warnings

</div>
SSL options are not applicable to unix domain sockets, named pipes or vsock. \
Do not assume that you can just enable SSL to make your connection secure.


***

For detailed instructions on using your own CA, click on:
<details markdown="1">
  <summary>Securing SSL with self-signed CA and certificates</summary>

See [The Most Dangerous Code in the World: Validating SSL Certificates in Non-Browser Software](https://www.cs.utexas.edu/~shmat/shmat_ccs12.pdf) and [Beware of Unverified TLS Certificates in PHP & Python](https://blog.sucuri.net/2016/03/beware-unverified-tls-certificates-php-python.html). \
See also: [Fallout from the Python certificate verification change](https://lwn.net/Articles/666353/).

Since the server certificate will not be signed by any recognized certificate authorities, you will need to send the verification data to the client via some other means... This will not be handled by xpra, it simply cannot be. (same as the AES key, at which point... you might as well use [AES](AES.md)?)
```
# generate your CA key and certificate:
openssl genrsa -out ca.key 4096
# (provide the 'Common Name', ie: 'Example Internal CA')
openssl req -new -x509 -days 365 -key ca.key -out ca.crt
# generate your server key:
openssl genrsa -out server.key 4096
# make a signing request from the server key:
# (you must provide the 'Common Name' here, ie: 'localhost' or 'test.internal')
openssl req -new -key server.key -out server.csr
# sign it with your CA key:
openssl x509 -req -days 365 \
        -in server.csr -out server.crt \
        -CA ca.crt -CAkey ca.key \
        -CAserial ./caserial -CAcreateserial
# verify it (it should print "OK"):
openssl verify -CAfile ca.crt ./server.crt
```
You can now start your xpra server using this key:
```
xpra seamless --start=xterm \
     --bind-tcp=0.0.0.0:10000 \
     --ssl-cert=`pwd`/server.crt --ssl-key=`pwd`/server.key
```
Use openssl to verify that this xpra server uses SSL and that the certificate can be verified using the "ca.crt" authority file: (it should print `Verify return code: 0 (ok)`):
```
openssl s_client -connect 127.0.0.1:10000  -CAfile /path/to/ca.crt < /dev/null
```
Connect the xpra client:
```
xpra attach ssl://localhost:10000/ --ssl-ca-certs=/path/to/ca.crt
```

### Sending the CA data

In some cases, it may be desirable to supply the CA certificate on the command line, in a URL string or in a session file. Here's how.

Convert a CA file to a hexadecimal string:
```
python3 -c "import sys,binascii;print(binascii.hexlify(open(sys.argv[1],'rb').read()).decode())" ca.crt
```
Convert hex back to data to verify (only part of the data shown here):
```
python3 -c "import sys,binascii;print(binascii.unhexlify(sys.argv[1]).decode())" \
2d2d2d2d2d424547494e2043455254494649434154452d2d2d2d2d0a4d4949
```
Use it directly in the xpra command:
```
xpra attach ssl://localhost:10000/ \
     --ssl-ca-data=2d2d2d2d2d424547494e...4452d2d2d2d2d0a
```
Alternatively, place all of these in a connection file you can just double-click on:
```
cat > ssl-test.xpra <<EOF
host=localhost
autoconnect=true
port=10000
mode=ssl
ssl-ca-data=2d2d2d2d2d424547494e...4452d2d2d2d2d0a
EOF
```
The cadata can also be encoded using base64, which is shorter:
```
python3 -c 'import sys,base64;print("base64:"+(base64.b64encode(open(sys.argv[1], "rb").read()).decode()))' ca.crt
```
</details>
