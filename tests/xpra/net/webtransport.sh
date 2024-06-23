#!/bin/bash

HOST="localhost"
CERT="./tests/ssl_cert.pem"
KEY="./tests/ssl_key.pem"
HASH="./tests/ssl_cert-hash.b64"
PORT=20000


if [ ! -d "aioquic" ]; then
  git clone https://github.com/aiortc/aioquic
fi
cd aioquic

if [ ! -e "${CERT}" ]; then
  echo "generating the SSL certificate"
  openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -x509 -nodes -days 10 \
    -out ${CERT} -keyout ${KEY} -subj '/CN=Test Certificate' -addext "subjectAltName = DNS:${HOST}"
fi

# generate the hash:
openssl x509 -in "${CERT}" -pubkey -noout | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | openssl enc -base64 > ${HASH}
HASH_VALUE=`cat ${HASH}`

python3 ./examples/http3_server.py --host ${HOST} --port ${PORT} -c ${CERT} -k ${KEY} -v &

cat > examples/index.html <<EOF
<html>
  <head>
    <title>WebTransport Test Page</title>
  </head>
  <body>
    <span id="output"></span>
    <script>
      const output_span = document.getElementById("output");
      const hash = "${HASH_VALUE}";
      function base64ToArrayBuffer(base64) {
          var binaryString = atob(base64);
          var bytes = new Uint8Array(binaryString.length);
          for (var i = 0; i < binaryString.length; i++) {
              bytes[i] = binaryString.charCodeAt(i);
          }
          return bytes.buffer;
      }
      function log(message) {
        console.log(message);
        output_span.innerHTML = output_span.innerHTML + "<br />" + message;
      }
      const url = "https://${HOST}:${PORT}/wt";
      log("opening WebTransport connection to "+url);
      log("using certificate hash ${HASH_VALUE}");
      const wt = new WebTransport(url, {
              serverCertificateHashes: [
                {
                  algorithm: 'sha-256',
                  value: base64ToArrayBuffer(hash),
                }
              ]
            });
      wt.ready.then(() => log("OK")
      ).catch(error => log("ERROR: "+error));
    </script>
  <body>
</html>
EOF

google-chrome-beta --enable-experimental-web-platform-features --origin-to-force-quic-on=${HOST}:${PORT} --ignore-certificate-errors-spki-list=${HASH_VALUE} ./examples/index.html &

firefox ./examples/index.html &
