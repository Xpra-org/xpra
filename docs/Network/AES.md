Use this option if you can securely distribute the AES key to each client.\
It is somewhat similar to [SSL](./SSL.md) mode with a self-signed certificate.

Xpra's AES [encryption](./Encryption.md) layer uses the [python cryptography](https://pypi.python.org/pypi/cryptography) library to encrypt the network packets with [AES](http://en.wikipedia.org/wiki/Advanced_Encryption_Standard)(Advanced Encryption Standard) [CBC mode](http://en.wikipedia.org/wiki/Block_cipher_mode_of_operation#Cipher-block_chaining_.28CBC.29) (Cipher-block 
chaining).

The encryption key can be stored in a keyfile or specified using the `keydata` socket option. If neither is present and an authentication module was used, the password will be used as key data.\
The key data is stretched using [PBKDF2](http://en.wikipedia.org/wiki/PBKDF2)(Password-Based Key Derivation Function 2).\
The salts used are generated using Python's [uuid.uuid4()](http://docs.python.org/2/library/uuid.html#uuid.uuid4)

# Usage Example
generate a key:
```
uuidgen > ./key.txt
```
start a server:
```
xpra start --start=xterm \
     --bind-tcp=0.0.0.0:10000,encryption=AES,keyfile=key.txt
```
* client:
```
xpra attach "tcp://localhost:10000/?encryption=AES&keyfile=./key.txt"
```

## Older syntax
Prior to version 4.1, the encryption is configured globally, for all TCP sockets, using the following syntax:
```
xpra start --start=xterm \
     --bind-tcp=0.0.0.0:10000 \
     --tcp-encryption=AES --tcp-encryption-keyfile=key.txt
```
```
xpra attach tcp://$HOST:10000 --tcp-encryption=AES --tcp-encryption-keyfile=./key.txt
```

## keydata
With newer versions, instead of using the `keyfile` option, it is also possible to inline the `keydata` value in the bind and attach strings:
* `keydata=0x...` for hexadecimal encoded keys
* `keydata=base64:...` for base64 encoded keys
* `keydata=...` for plain text keys

One major disadvantage is that the key data may be leaked in the process list.\
However, it may be easier in some cases to generate commands that do not require extra files to run.


# Debugging
To verify that your client connection is using AES, look for `cipher=AES`:
```
xpra info | grep cipher=
```

To enable debugging, use the `-d crypto` [debug logging](../Usage/Logging.md) option.
