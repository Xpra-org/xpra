#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import json
import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from xpra.auth.email import Authenticator as EmailAuthenticator
from xpra.auth.sms import Authenticator, parse_headers, validate_number
from xpra.net.digest import gendigest, get_digests, get_salt, get_salt_digests
from xpra.util.objects import typedict

BREVO = "https://api.brevo.com/v3/transactionalSMS/send"


class SMSAuthTest(unittest.TestCase):

    def setUp(self):
        for cls in (Authenticator, EmailAuthenticator):
            with cls.SEND_LOCK:
                cls.SENDS.clear()
        self.requests = []
        self.status = 201
        self.opener_patch = patch("xpra.auth.sms.build_opener", side_effect=self.build_opener)
        self.opener_patch.start()
        self.addCleanup(self.opener_patch.stop)
        self.random_patch = patch("xpra.auth.code_base.secrets.randbelow", return_value=123)
        self.random_patch.start()
        self.addCleanup(self.random_patch.stop)

    def build_opener(self, *handlers):
        opener = MagicMock()

        def open_request(request, timeout):
            self.requests.append((request, timeout, handlers))
            response = MagicMock()
            response.status = self.status
            response.read.return_value = b'{"messageId": 1}'
            response.__enter__.return_value = response
            return response
        opener.open.side_effect = open_request
        return opener

    def auth(self, **kwargs):
        options = {
            "username": "alice", "number": "+33680065433", "url": BREVO, "from": "Xpra",
            "connection": SimpleNamespace(remote=("192.0.2.1", 1000)),
        }
        options.update(kwargs)
        auth = Authenticator(**options)
        self.addCleanup(auth.cleanup)
        return auth

    def begin(self, auth):
        challenge = auth.get_challenge(get_digests())
        auth.choose_salt_digest(get_salt_digests())
        return challenge

    def response(self, auth, value):
        client_salt = get_salt(32)
        salt = gendigest(auth.salt_digest, client_salt, auth.salt)
        return typedict({
            "challenge_response": gendigest(auth.digest, value, salt), "challenge_client_salt": client_salt,
        })

    def request(self):
        return self.requests[-1][0]

    def json_body(self):
        return json.loads(self.request().data)

    def temp_file(self, data):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
            f.write(data)
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_fixed_success(self):
        auth = self.auth()
        salt, digest = self.begin(auth)
        self.assertTrue(salt)
        self.assertTrue(digest.startswith("hmac+"))
        self.assertFalse(auth.passed)
        request = self.request()
        self.assertEqual(request.full_url, BREVO)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(self.json_body(), {
            "sender": "Xpra", "recipient": "33680065433", "content": "Your Xpra verification code is 000123",
        })
        self.assertEqual(self.requests[-1][1], 10)
        self.assertTrue(auth.authenticate(self.response(auth, "000123")))
        self.assertTrue(auth.passed)
        self.assertEqual(auth.code, "")
        self.assertEqual(repr(auth), "sms")
        self.assertEqual(auth.prompt, "SMS verification code")

    def test_wrong_code_is_final(self):
        auth = self.auth()
        self.begin(auth)
        wrong = self.response(auth, "000124")
        correct = self.response(auth, "000123")
        self.assertFalse(auth.authenticate(wrong))
        self.assertFalse(auth.authenticate(correct))
        self.assertFalse(auth.passed)

    def test_replay_and_expiry(self):
        auth = self.auth()
        self.begin(auth)
        caps = self.response(auth, "000123")
        self.assertTrue(auth.authenticate(caps))
        self.assertFalse(auth.authenticate(caps))
        auth = self.auth(number="+33680065434")
        with patch("xpra.auth.code_base.monotonic", return_value=1000):
            self.begin(auth)
        with patch("xpra.auth.code_base.monotonic", return_value=1120):
            self.assertFalse(auth.authenticate(self.response(auth, "000123")))

    def test_prompt_flow(self):
        for country, entered, expected in (
            ("", "+44 7700 900123", "+447700900123"),
            ("", "0044 7700-900123", "+447700900123"),
            ("+33", "06 80 06 54 33", "+33680065433"),
            ("+33", "(0)6.80.06.54.33", "+33680065433"),
            ("+33", "+44 7700 900123", "+447700900123"),
        ):
            with self.subTest(entered=entered):
                with Authenticator.SEND_LOCK:
                    Authenticator.SENDS.clear()
                auth = self.auth(mode="prompt", number="", country=country)
                self.assertEqual(self.begin(auth)[1], "xor")
                self.assertIn("phone number", auth.prompt)
                count = len(self.requests)
                self.assertTrue(auth.authenticate(self.response(auth, entered)))
                self.assertFalse(auth.passed)
                self.assertEqual(len(self.requests), count + 1)
                self.assertEqual(self.json_body()["recipient"], expected[1:])
                salt, digest, prompt = auth.get_next_challenge()
                self.assertTrue(digest.startswith("hmac+"))
                self.assertEqual(prompt, "SMS verification code")
                auth.choose_salt_digest(get_salt_digests())
                self.assertTrue(auth.authenticate(self.response(auth, "000123")))
                self.assertTrue(auth.passed)

    def test_prompt_rejects_bad_numbers(self):
        for number in ("680065433", "+0680065433", "+12", "+1234567890123456", "abc", "+33 6 80;06", "+33\n680065433", "x" * 40):
            with self.subTest(number=number):
                auth = self.auth(mode="prompt", number="")
                self.begin(auth)
                self.assertFalse(auth.authenticate(self.response(auth, number)))
                self.assertEqual(auth.get_next_challenge(), ())
        self.assertEqual(self.requests, [])

    def test_validate_number(self):
        self.assertEqual(validate_number("+1 (555) 010-0199"), "+15550100199")
        self.assertEqual(validate_number("0033680065433"), "+33680065433")
        for value in ("", "33680065433", "+", "+0123456789", "+33 6 80 é", "+3368006543312345", "+33680065433\x00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_number(value)

    def test_exec_lookup(self):
        command = f"{sys.executable} -c \"import sys; print('+1555010' + str(len(sys.argv[1])).zfill(4))\""
        self.begin(self.auth(mode="lookup", lookup="exec", command=command, number="", remote={"username": "bob"}))
        self.assertEqual(self.json_body()["recipient"], "15550100003")

    def test_sql_lookup_query(self):
        engine = MagicMock()
        result = engine.connect.return_value.__enter__.return_value.execute.return_value.__enter__.return_value
        result.fetchmany.return_value = [("+33 6 80 06 54 33",)]
        sqlalchemy = SimpleNamespace(create_engine=MagicMock(return_value=engine), text=MagicMock(return_value="query"))
        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}):
            self.begin(self.auth(mode="lookup", lookup="sql", uri="sqlite:///users.db", number=""))
        sqlalchemy.text.assert_called_once_with("SELECT phone FROM users WHERE username=:username")
        self.assertEqual(self.json_body()["recipient"], "33680065433")

    def test_lookup_rejects_bad_numbers(self):
        command = f"{sys.executable} -c \"print('not a number')\""
        auth = self.auth(mode="lookup", lookup="exec", command=command, number="")
        with self.assertRaisesRegex(ValueError, "^cannot issue sms authentication challenge$"):
            self.begin(auth)
        self.assertEqual(self.requests, [])

    def test_json_escaping(self):
        body = self.temp_file('{"to": "{to}", "text": "{message}", "from": "{from}", "nested": {"code": "{code}"}}')
        message = 'say "{to}" \\ code: {code} {message}'
        self.begin(self.auth(**{"body-file": body, "message": message, "from": "A+B"}))
        self.assertEqual(self.json_body(), {
            "to": "+33680065433", "text": 'say "{to}" \\ code: 000123 {message}', "from": "A+B",
            "nested": {"code": "000123"},
        })

    def test_form_escaping(self):
        body = self.temp_file("To={to}&From={from}&Body={message}\n")
        self.begin(self.auth(**{"body-format": "form", "body-file": body, "message": "a&b=c {code}"}))
        request = self.request()
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        self.assertEqual(parse_qs(request.data.decode()), {
            "To": ["+33680065433"], "From": ["Xpra"], "Body": ["a&b=c 000123"],
        })

    def test_get_url_placeholders(self):
        url = "https://sms.example.com/send?to={to_digits}&text={message}"
        self.begin(self.auth(url=url, method="get"))
        request = self.request()
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.full_url, "https://sms.example.com/send?to=33680065433&text=Your%20Xpra%20verification%20code%20is%20000123")

    def test_headers_file(self):
        headers = self.temp_file("# brevo\napi-key: xkeysib-secret\n\nAuthorization: Bearer a:b\n")
        with patch("xpra.auth.sys_auth_base.log") as log:
            self.begin(self.auth(**{"headers-file": headers}))
            for call in log.mock_calls:
                self.assertNotIn("xkeysib-secret", repr(call))
        request = self.request()
        self.assertEqual(request.get_header("Api-key"), "xkeysib-secret")
        self.assertEqual(request.get_header("Authorization"), "Bearer a:b")
        self.assertEqual(parse_headers("Content-Type: text/plain"), [("Content-Type", "text/plain")])
        for invalid in ("no-colon", "bad name: value", ": value", "empty:", "x: a\x7fb"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_headers(invalid)

    def test_headers_are_reread_for_each_send(self):
        headers = self.temp_file("api-key: one\n")
        auth = self.auth(**{"headers-file": headers})
        with open(headers, "w", encoding="utf-8") as f:
            f.write("api-key: two\n")
        self.begin(auth)
        self.assertEqual(self.request().get_header("Api-key"), "two")

    def test_https_handler_and_redirects(self):
        self.begin(self.auth())
        handlers = self.requests[-1][2]
        self.assertEqual(sorted(type(h).__name__ for h in handlers), ["HTTPSHandler", "NoRedirectHandler"])

    def test_provider_failures_are_redacted(self):
        errors = (
            HTTPError(BREVO, 400, "secret reply", {}, None),
            URLError("connection refused"),
            TimeoutError("timed out"),
            OSError("network down"),
        )
        for i, error in enumerate(errors):
            with self.subTest(error=error):
                self.opener_patch.stop()
                with patch("xpra.auth.sms.build_opener") as build:
                    build.return_value.open.side_effect = error
                    auth = self.auth(number=f"+3368006543{i}")
                    with self.assertRaisesRegex(ValueError, "^cannot issue sms authentication challenge$"):
                        self.begin(auth)
                self.opener_patch.start()
                self.assertEqual(auth.code, "")

    def test_unexpected_status(self):
        self.status = 204
        self.begin(self.auth())
        self.status = 101
        with self.assertRaises(ValueError):
            self.begin(self.auth(number="+33680065499"))

    def test_invalid_configuration(self):
        body = self.temp_file('{"broken": {message}}')
        invalid = (
            {"url": ""}, {"url": "ftp://example.com/"}, {"url": "https:///path"},
            {"url": "http://example.com/"}, {"url": "https://user:pass@example.com/"},
            {"http-insecure": "maybe"}, {"method": "DELETE"}, {"body-format": "xml"},
            {"body-format": "form"}, {"method": "GET", "body-file": body}, {"body-file": body},
            {"body-file": "/nonexistent/body"}, {"headers-file": "/nonexistent/headers"},
            {"from": "far too long sender"}, {"from": "bad;sender"}, {"message": "no code"},
            {"message": "x" * 150 + "{code}"}, {"country": "33"}, {"country": "+33", "mode": "fixed"},
            {"number": ""}, {"number": "12345"}, {"mode": "prompt"}, {"mode": "derived"},
            {"mode": "lookup", "lookup": "exec"}, {"http-timeout": 0},
            {"url": "http://127.0.0.1/", "http-insecure": "yes", "http-ssl-ca-certs": "/ca.pem"},
            {"http-ssl-unknown": "x"},
        )
        for options in invalid:
            with self.subTest(options=options), self.assertRaises((ValueError, OSError)):
                self.auth(**options)
        self.assertEqual(self.requests, [])

    def test_separate_send_limits(self):
        self.begin(self.auth())
        with self.assertRaises(ValueError):
            self.begin(self.auth())
        self.assertIn(("recipient", "+33680065433"), Authenticator.SENDS)
        self.assertNotIn(("recipient", "+33680065433"), EmailAuthenticator.SENDS)
        self.assertIsNot(Authenticator.SENDS, EmailAuthenticator.SENDS)

    def test_manager_flow_with_client(self):
        from xpra.challenge.prompt import Handler
        from xpra.net.common import Packet
        from xpra.server.auth import AuthenticationManager, get_auth_modules
        from unit.auth.auth_loopback_util import make_challenge_client
        server = MagicMock()
        server.subsystems = {"network": MagicMock()}
        manager = AuthenticationManager(server)
        manager.auth_classes["ssl"] = get_auth_modules("ssl", (
            "password(value=primary-secret,username=alice)",
            f"sms(mode=prompt,country=+33,url={BREVO},from=Xpra)",
        ))
        proto = MagicMock()
        proto._conn = SimpleNamespace(socktype="ssl", socktype_wrapped="ssl", options={}, remote=("192.0.2.1", 1))
        proto.is_closed.return_value = False
        proto.authenticators = ()
        packets = []
        proto.send_now.side_effect = packets.append
        caps = typedict({"username": "alice", "digest": get_digests(), "salt-digest": get_salt_digests()})
        answers = iter(("primary-secret", "06 80 06 54 33", "000123"))
        captured, errors = [], []
        handlers = [Handler(challenge_prompt_function=lambda _label: next(answers)) for _ in range(3)]
        client = make_challenge_client(handlers[0], "alice", captured, errors)
        client.challenge_handlers = handlers
        with patch.object(AuthenticationManager, "setup_encryption", return_value={}), \
                patch("xpra.server.auth.GLib.idle_add") as accepted, patch("xpra.server.auth.GLib.timeout_add") as failed:
            manager.verify_auth(proto, Packet("hello", dict(caps)), caps)
            while packets:
                self.assertLess(len(captured), 3)
                packet = packets.pop(0)
                self.assertTrue(client.validate_challenge_packet(packet))
                client.do_process_challenge(packet)
                self.assertFalse(errors)
                response, client_salt = captured[-1]
                caps.update({"challenge_response": response, "challenge_client_salt": client_salt})
                manager.verify_auth(proto, Packet("hello", dict(caps)), caps)
            for auth in proto.authenticators:
                self.addCleanup(auth.cleanup)
        self.assertEqual((accepted.call_count, failed.call_count), (1, 0))
        self.assertEqual(len(captured), 3)
        self.assertEqual(self.json_body()["recipient"], "33680065433")

    def test_module_options_are_consumed(self):
        from xpra.auth.auth_helper import get_auth_module
        from xpra.auth.option import AUTH_OPTION_KEYS
        headers = self.temp_file("api-key: x\n")
        _name, _module, cls, options = get_auth_module(
            f"sms(mode=prompt,country=+33,url={BREVO},from=Xpra,headers-file={headers},http-timeout=5,http-ssl-check-hostname=yes)"
        )
        options[AUTH_OPTION_KEYS] = tuple(key for key in options if key != "exec_cwd")
        with patch("xpra.auth.option.log") as log:
            auth = cls(username="alice", **options)
            self.addCleanup(auth.cleanup)
            log.warn.assert_not_called()
        self.assertEqual(auth.country, "+33")


class Recorder(BaseHTTPRequestHandler):
    requests: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.requests.append((self.path, self.headers, body))
        if self.path == "/redirect":
            self.send_response(307)
            self.send_header("Location", "/other")
            self.end_headers()
            return
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"messageId": 1}')

    def log_message(self, *_args):
        pass


class SMSLoopbackTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Recorder.requests.clear()
        with Authenticator.SEND_LOCK:
            Authenticator.SENDS.clear()
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
            f.write("api-key: xkeysib-secret\n")
        self.addCleanup(os.unlink, f.name)
        self.headers = f.name

    def auth(self, path):
        auth = Authenticator(username="alice", number="+33680065433", url=self.base + path, **{
            "http-insecure": "yes", "headers-file": self.headers, "from": "Xpra",
            "connection": SimpleNamespace(remote=("127.0.0.1", 1)),
        })
        self.addCleanup(auth.cleanup)
        return auth

    def test_real_request(self):
        auth = self.auth("/v3/transactionalSMS/send")
        auth.get_challenge(get_digests())
        self.assertEqual(len(Recorder.requests), 1)
        path, headers, body = Recorder.requests[0]
        self.assertEqual(path, "/v3/transactionalSMS/send")
        self.assertEqual(headers["api-key"], "xkeysib-secret")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body)["recipient"], "33680065433")
        self.assertEqual(json.loads(body)["content"], "Your Xpra verification code is " + auth.code)

    def test_redirect_is_not_followed(self):
        auth = self.auth("/redirect")
        with self.assertRaises(ValueError):
            auth.get_challenge(get_digests())
        self.assertEqual([r[0] for r in Recorder.requests], ["/redirect"])
        self.assertEqual(auth.code, "")

    def test_connection_refused(self):
        auth = Authenticator(username="alice", number="+33680065433", url="http://127.0.0.1:1/", **{"http-insecure": "yes"})
        self.addCleanup(auth.cleanup)
        with self.assertRaisesRegex(ValueError, "^cannot issue sms authentication challenge$"):
            auth.get_challenge(get_digests())


if __name__ == "__main__":
    unittest.main()
