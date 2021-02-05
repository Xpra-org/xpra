# Basic Example

start a server with TCP and SSL support using an existing certificate `cert.pem` (see below for generating one):
```
xpra start --start=xterm \
     --bind-tcp=0.0.0.0:10000 \
     --ssl-cert=/path/to/ssl-cert.pem
```
connect a client:
```
xpra attach ssl://127.0.0.1:10001/
```
To avoid this error when the server uses a self signed certificate:
```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed (_ssl.c:590)
```
You can:
* *temporarily* add `--ssl-server-verify-mode=none` to your client command line
* or copy the key to the client then use `ssl-ca-certs` to use it for validation:
```
   xpra attach ssl://host:10000/ --ssl-ca-certs=./cert.pem
```

## Generating a self signed certificate
```
openssl req -new -x509 -days 365 -nodes -out cert.pem -keyout key.pem -sha256
cat key.pem cert.pem > ssl-cert.pem
```
For trusting your own certificates and testing with localhost, see [certificates for localhost](https://letsencrypt.org/docs/certificates-for-localhost/)

## Socket upgrades
Once a server is configured for `SSL` - usually by adding the `--ssl-cert` option, its TCP sockets (`bind-tcp` option) can automatically be upgraded to:
* `ssl`, obviously
* `http` and `ws` (`websockets`) connections can be upgraded to `https` and `wss` (`secure websockets`)

The same way, any `ws` sockets specified with the `bind-ws` option can then be upgraded to `wss`.

This allows a single port to be used with multiple protocols (including also [SSH](./SSH.md)), which can more easily go through some firewalls and may be required by some network policies. Client certificates can also be used for authentication.

## SSL options
There are many options to configure and certificates to deal with.
See [https://docs.python.org/2/library/ssl.html], on which this is based.

For more details see [#1252](../https://github.com/Xpra-org/xpra/issues/1252).

## Default Certificate
When using the binary packages from https://xpra.org, a self-signed SSL certificate will be generated during the first installation.\
It is placed in:
* `/etc/xpra/ssl-cert.pem` on Posix platforms
* `C:\ProgramData\Xpra\ssl-cert.pem` on MS Windows
* `/Library/Application Support/Xpra/ssl-cert.pem` on Mac OS

## Warnings
SSL options are not applicable to unix domain sockets, named pipes or vsock. \
Do not assume that you can just enable SSL to make your connection secure.


***

# Securing SSL with self signed CA and certificates

See [The Most Dangerous Code in the World: Validating SSL Certificates in Non-Browser Software](https://www.cs.utexas.edu/~shmat/shmat_ccs12.pdf) and [Beware of Unverified TLS Certificates in PHP & Python](https://blog.sucuri.net/2016/03/beware-unverified-tls-certificates-php-python.html). \
See also: [Fallout from the Python certificate verification change](https://lwn.net/Articles/666353/).

Since the server certificate will not be signed by any recognized certificate authorities, you will need to send the verification data to the client via some other means... This will no be handled by xpra, it simply cannot be. (same as the AES key, at which point... you might as well use [AES](./AES)?)
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
xpra start --start=xterm \
     --bind-tcp=0.0.0.0:10000 \
     --ssl-cert=`pwd`/server.crt --ssl-key=`pwd`/server.key
```
Use openssl to verify that this xpra server uses SSL and that the certificate can be verified using the "ca.crt" authority file: (it should print `Verify return code: 0 (ok)`):
```
openssl s_client -connect 127.0.0.1:10000  -CAfile /path/to/ca.crt < /dev/null
```
Connect the xpra client:
```
xpra attach ssl:localhost:10000 --ssl-ca-cert=/path/to/ca.crt
```

## Sending the CA data

In some cases, it may be desirable to supply the CA certificate on the command line, in a URL string or in a session file. Here's how.

Convert a CA file to a hexadecimal string:
```
python -c "import sys,binascii;print(binascii.hexlify(open(sys.argv[1]).read()))" ca.crt
```
Convert hex back to data to verify (only part of the data shown here):
```
python -c "import sys,binascii;print binascii.unhexlify(sys.argv[1])" \
2d2d2d2d2d424547494e2043455254494649434154452d2d2d2d2d0a4d4949
```
Use it directly in the xpra command:
```
xpra attach ssl:localhost:10000 \
     --ssl-ca-data=2d2d2d2d2d424547494e...4452d2d2d2d2d0a
```
Alternatively, place all of these in a connection file you can just double click on:
```
echo > ssl-test.xpra <<EOF
host=localhost
autoconnect=true
port=10000
mode=ssl
ssl-ca-data=2d2d2d2d2d424547494e...4452d2d2d2d2d0a
EOF
```
The cadata can also be encoded using base64, which is more dense:
```
$ python -c 'import sys,base64;print("base64:"+(base64.b64encode(open(sys.argv[1], "rb").read()).decode()))' ca.crt
```
