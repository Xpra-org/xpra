#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib.util
import base64
import os
import shlex
import shutil
import smtplib
import ssl
import subprocess
import sys
import tempfile
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from xpra.auth.email import Authenticator, lookup_command, validate_address
from xpra.challenge.prompt import Handler
from xpra.net.common import Packet
from xpra.net.digest import gendigest, get_digests, get_salt, get_salt_digests
from xpra.net.packet_type import CHALLENGE
from xpra.util.objects import typedict
from unit.auth.auth_loopback_util import make_challenge_client


class EmailAuthTest(unittest.TestCase):

    def setUp(self):
        with Authenticator.SEND_LOCK:
            Authenticator.SENDS.clear()
        self.smtp_patch = patch("xpra.auth.email.smtplib.SMTP")
        self.smtp_class = self.smtp_patch.start()
        self.addCleanup(self.smtp_patch.stop)
        self.smtp = self.smtp_class.return_value.__enter__.return_value
        self.smtp.send_message.return_value = {}
        self.random_patch = patch("xpra.auth.code_base.secrets.randbelow", return_value=123)
        self.random_patch.start()
        self.addCleanup(self.random_patch.stop)

    def auth(self, **kwargs):
        options = {
            "username": "alice", "address": "alice@example.com", "smtp-host": "smtp.example.com",
            "from": "xpra@example.com", "connection": SimpleNamespace(remote=("192.0.2.1", 1000)),
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

    def message(self):
        return self.smtp.send_message.call_args.args[0]

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
        self.assertEqual(self.message()["To"], "alice@example.com")
        self.assertIn("000123", self.message().get_content())
        self.assertTrue(auth.authenticate(self.response(auth, "000123")))
        self.assertTrue(auth.passed)
        self.assertEqual(auth.code, "")
        self.assertEqual(auth.get_next_challenge(), ())
        self.assertIsNone(auth.get_sessions())
        self.assertEqual(auth.get_uid(), -1)
        self.assertEqual(auth.get_gid(), -1)

    def test_wrong_code_is_final(self):
        auth = self.auth()
        self.begin(auth)
        wrong = self.response(auth, "wrong")
        correct = self.response(auth, "000123")
        self.assertFalse(auth.authenticate(wrong))
        self.assertFalse(auth.authenticate(correct))
        self.assertFalse(auth.passed)
        self.assertEqual(auth.code, "")
        self.assertIsNone(auth.salt)
        self.assertEqual(auth.get_challenge(get_digests()), (b"", ""))

    def test_replay_after_success(self):
        auth = self.auth()
        self.begin(auth)
        caps = self.response(auth, "000123")
        self.assertTrue(auth.authenticate(caps))
        self.assertFalse(auth.authenticate(caps))

    def test_expiry_boundary(self):
        for offset, valid in ((119.999, True), (120, False), (121, False)):
            with self.subTest(offset=offset):
                auth = self.auth(address=f"user{offset}@example.com")
                with patch("xpra.auth.code_base.monotonic", return_value=1000):
                    self.begin(auth)
                caps = self.response(auth, "000123")
                with patch("xpra.auth.code_base.monotonic", return_value=1000 + offset):
                    self.assertEqual(auth.authenticate(caps), valid)
                self.assertEqual(auth.code, "")

    def test_expiry_starts_after_delivery(self):
        clock = [1000]
        self.smtp.send_message.side_effect = lambda *a, **kw: clock.__setitem__(0, 1020)
        auth = self.auth()
        with patch("xpra.auth.code_base.monotonic", side_effect=lambda: clock[0]):
            self.begin(auth)
        self.assertEqual(auth.expires, 1140)

    def test_fresh_code_and_connection_isolation(self):
        first = self.auth(address="one@example.com")
        second = self.auth(address="two@example.com")
        with patch("xpra.auth.code_base.secrets.randbelow", side_effect=(1, 2)):
            self.begin(first)
            self.begin(second)
        self.assertFalse(second.authenticate(self.response(second, "000001")))
        self.assertTrue(first.authenticate(self.response(first, "000001")))

    def test_duplicate_challenge_does_not_send_again(self):
        auth = self.auth()
        self.begin(auth)
        self.assertEqual(auth.get_challenge(get_digests()), (b"", ""))
        self.assertEqual(self.smtp.send_message.call_count, 1)

    def test_missing_response_invalidates_code(self):
        auth = self.auth()
        self.begin(auth)
        self.assertFalse(auth.authenticate(typedict()))
        self.assertEqual(auth.code, "")
        self.assertIsNone(auth.salt)

    def test_cleanup(self):
        auth = self.auth()
        self.begin(auth)
        caps = self.response(auth, "000123")
        auth.cleanup()
        self.assertEqual(auth.code, "")
        self.assertFalse(auth.authenticate(caps))
        self.assertEqual(auth.get_next_challenge(), ())

    def test_cleanup_during_delivery(self):
        auth = self.auth()
        self.smtp.send_message.side_effect = lambda *a, **kw: auth.cleanup()
        with self.assertRaises(ValueError):
            self.begin(auth)
        self.assertEqual(auth.code, "")
        self.assertIsNone(auth.salt)
        self.assertFalse(auth.passed)

    def test_prompt_flow(self):
        auth = self.auth(mode="prompt", address="")
        self.assertEqual(self.begin(auth)[1], "xor")
        self.smtp.send_message.assert_not_called()
        self.assertTrue(auth.authenticate(self.response(auth, "other@example.net")))
        self.assertFalse(auth.passed)
        salt, digest, prompt = auth.get_next_challenge()
        self.assertEqual(salt, auth.salt)
        self.assertTrue(digest.startswith("hmac+"))
        self.assertEqual(prompt, "Email verification code")
        self.assertEqual(self.message()["To"], "other@example.net")
        self.assertEqual(auth.get_next_challenge(), ())
        auth.choose_salt_digest(get_salt_digests())
        self.assertTrue(auth.authenticate(self.response(auth, "000123")))
        self.assertTrue(auth.passed)

    def test_domain_prompt_and_alias(self):
        for domain in ("@Example.com", r"\@Example.com"):
            with self.subTest(domain=domain):
                with Authenticator.SEND_LOCK:
                    Authenticator.SENDS.clear()
                auth = self.auth(mode="prompt", address=domain)
                self.begin(auth)
                self.assertIn("@example.com", auth.prompt)
                self.assertTrue(auth.authenticate(self.response(auth, "bob")))
                self.assertFalse(auth.passed)
                self.assertEqual(self.message()["To"], "bob@example.com")

    def test_prompt_rejects_bad_addresses(self):
        for address in ("x@elsewhere.com", "bob\nBcc:victim", "a,b", "a b", "a" * 255):
            with self.subTest(address=address):
                auth = self.auth(mode="prompt", address="@example.com")
                self.begin(auth)
                self.assertFalse(auth.authenticate(self.response(auth, address)))
                self.assertFalse(auth.passed)
                self.assertEqual(auth.get_next_challenge(), ())
        self.smtp.send_message.assert_not_called()

    def test_invalid_address_validation(self):
        invalid = (
            "", "abc", "a@@b", "Name <a@b.com>", "a@b,c@d", "a@b;c@d", "a\r\nBcc:x@y.com",
            "a b@example.com", "a@bad_domain", "a@-bad.com", "a@bad-.com", "a@bad..com", "a@bad.com.",
            ".a@example.com", "a.@example.com", "a..b@example.com", "é@example.com", "a@é.com", "a\x00@b.com",
            "a" * 65 + "@example.com", "a@" + "b" * 64 + ".com", "a@" + ".".join(["b" * 63] * 4),
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_address(value)
        self.assertEqual(validate_address("Alice+tag@EXAMPLE.COM"), "Alice+tag@example.com")

    def test_derived_address_uses_login_username(self):
        auth = self.auth(mode="derived", address="@example.com", remote={"username": "bob"})
        self.begin(auth)
        self.assertEqual(self.message()["To"], "bob@example.com")

    def test_derived_rejects_bad_username(self):
        for username in ("other@elsewhere.com", "Name <x>", "", "a,b"):
            with self.subTest(username=username):
                auth = self.auth(mode="derived", address="@example.com", remote={"username": username})
                with self.assertRaises(ValueError):
                    self.begin(auth)
        self.smtp.send_message.assert_not_called()

    def test_invalid_configuration(self):
        invalid = (
            {"mode": "unknown"}, {"address": ""}, {"smtp-host": ""}, {"from": "bad"}, {"smtp-security": "auto"},
            {"smtp-port": 0}, {"smtp-port": 65536}, {"smtp-timeout": 0}, {"timeout": -1}, {"digits": 5}, {"digits": 13},
            {"mode": "prompt", "address": "alice@example.com"}, {"mode": "derived", "address": ""},
            {"mode": "lookup"}, {"mode": "lookup", "lookup": "sql"}, {"mode": "lookup", "lookup": "exec"},
            {"smtp-username": "sender"}, {"smtp-password-file": "password.txt"}, {"lookup-timeout": 0},
        )
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.auth(**options)

    def test_hmac_required_before_sending(self):
        for mode, address in (("fixed", "alice@example.com"), ("prompt", "")):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.auth(mode=mode, address=address).get_challenge(("xor", "des"))
        self.smtp.send_message.assert_not_called()

    def test_prompt_requires_xor(self):
        auth = self.auth(mode="prompt", address="")
        with self.assertRaises(ValueError):
            auth.get_challenge(("hmac+sha256",))
        self.smtp.send_message.assert_not_called()

    def test_starttls(self):
        self.begin(self.auth())
        self.smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=10)
        self.assertEqual(self.smtp.ehlo.call_count, 2)
        context = self.smtp.starttls.call_args.kwargs["context"]
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.smtp.send_message.assert_called_once()
        self.assertEqual(self.smtp.send_message.call_args.kwargs["to_addrs"], ["alice@example.com"])
        self.smtp.set_debuglevel.assert_not_called()

    def test_implicit_tls(self):
        with patch("xpra.auth.email.smtplib.SMTP_SSL") as smtp_class:
            smtp = smtp_class.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            self.begin(self.auth(**{"smtp-security": "tls"}))
            self.assertEqual(smtp_class.call_args.args, ("smtp.example.com", 465))
            self.assertTrue(smtp_class.call_args.kwargs["context"].check_hostname)
            smtp.starttls.assert_not_called()
        self.smtp_class.assert_not_called()

    def test_plain_relay(self):
        self.begin(self.auth(**{"smtp-security": "plain"}))
        self.smtp_class.assert_called_once_with("smtp.example.com", 25, timeout=10)
        self.smtp.starttls.assert_not_called()
        self.smtp.login.assert_not_called()

    def test_custom_context_used_for_tls_and_starttls(self):
        for security in ("tls", "starttls"):
            with self.subTest(security=security), patch("xpra.auth.email.smtplib.SMTP_SSL") as smtp_ssl:
                smtp_ssl.return_value.__enter__.return_value.send_message.return_value = {}
                auth = self.auth(address=f"{security}@example.com", **{
                    "smtp-security": security, "smtp-ssl-ca-certs": "relay-ca.pem", "exec_cwd": "/tmp",
                })
                self.assertEqual(auth.smtp_ssl_options["ca-certs"], "/tmp/relay-ca.pem")
                context = ssl.create_default_context()
                with patch.object(Authenticator, "make_ssl_context", return_value=context) as make_context:
                    self.begin(auth)
                make_context.assert_called_once_with()
                if security == "tls":
                    self.assertIs(smtp_ssl.call_args.kwargs["context"], context)
                else:
                    self.smtp.starttls.assert_called_once_with(context=context)

    def test_smtp_ssl_settings_are_separate_from_listener_settings(self):
        auth = self.auth(**{"ssl-ca-certs": "/missing-listener-ca", "ssl-server-verify-mode": "none", "ssl-check-hostname": False})
        context = auth.make_ssl_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(auth.smtp_ssl_options, {})

    def test_ssl_verification_controls(self):
        context = self.auth(**{"smtp-ssl-server-verify-mode": "none"}).make_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)
        for value in (False, "false", "no", "0", "off"):
            with self.subTest(value=value):
                context = self.auth(**{"smtp-ssl-check-hostname": value}).make_ssl_context()
                self.assertFalse(context.check_hostname)
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        with self.assertRaises(ValueError):
            self.auth(**{"smtp-ssl-server-verify-mode": "none", "smtp-ssl-check-hostname": "yes"}).make_ssl_context()

    def test_ssl_protocol_cipher_and_flags(self):
        context = self.auth(**{
            "smtp-ssl-protocol": "TLS_CLIENT", "smtp-ssl-verify-flags": "X509_STRICT",
            "smtp-ssl-options": "NO_COMPRESSION", "smtp-ssl-ciphers": "ECDHE-RSA-AES256-GCM-SHA384",
        }).make_ssl_context()
        self.assertEqual(context.protocol, ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(context.verify_flags, ssl.VERIFY_X509_STRICT)
        self.assertEqual(context.options & ssl.OP_NO_COMPRESSION, ssl.OP_NO_COMPRESSION)
        self.assertTrue(context.check_hostname)
        # TLS 1.3 suites are not affected by set_ciphers(), and LibreSSL does not label them as "TLSv1.3"
        ciphers = [cipher["name"] for cipher in context.get_ciphers() if not cipher["name"].startswith("TLS_")]
        self.assertEqual(ciphers, ["ECDHE-RSA-AES256-GCM-SHA384"])

    def test_ssl_flag_lists_through_auth_options(self):
        from xpra.auth.auth_helper import get_auth_module
        _name, _module, cls, options = get_auth_module(
            "email(address=alice@example.com,smtp-host=localhost,from=xpra@example.com,"
            "smtp-ssl-verify-flags=X509_STRICT+X509_PARTIAL_CHAIN,smtp-ssl-options=NO_COMPRESSION+NO_RENEGOTIATION)"
        )
        auth = cls(username="alice", **options)
        self.addCleanup(auth.cleanup)
        context = auth.make_ssl_context()
        self.assertEqual(context.verify_flags, ssl.VERIFY_X509_STRICT | ssl.VERIFY_X509_PARTIAL_CHAIN)
        self.assertEqual(context.options & ssl.OP_NO_RENEGOTIATION, ssl.OP_NO_RENEGOTIATION)
        self.assertEqual(context.options & ssl.OP_NO_COMPRESSION, ssl.OP_NO_COMPRESSION)

    def test_invalid_ssl_options_do_not_connect(self):
        invalid = (
            {"smtp-ssl-protocol": "TLS_SERVER"}, {"smtp-ssl-protocol": "unknown"},
            {"smtp-ssl-verify-flags": "unknown"}, {"smtp-ssl-options": "unknown"},
            {"smtp-ssl-server-verify-mode": "unknown"}, {"smtp-ssl-ciphers": "unknown"},
            {"smtp-ssl-ca-certs": "/nonexistent/relay-ca.pem"}, {"smtp-ssl-ca-data": "not a certificate"},
        )
        for i, options in enumerate(invalid):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.begin(self.auth(address=f"user{i}@example.com", connection=None, **options))
        self.smtp_class.assert_not_called()

    def test_invalid_ssl_configuration(self):
        for options in (
            {"smtp-ssl-unknown": "yes"}, {"smtp-ssl-check-hostname": "perhaps"}, {"smtp-ssl-key": "key.pem"},
            {"smtp-ssl-key-password-file": "password"}, {"smtp-security": "plain", "smtp-ssl-ca-certs": "ca.pem"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.auth(**options)

    def test_smtp_login_order(self):
        password_file = self.temp_file("secret\r\n")
        self.begin(self.auth(**{"smtp-username": "sender", "smtp-password-file": password_file}))
        self.smtp.login.assert_called_once_with("sender", "secret")
        methods = [call[0] for call in self.smtp.mock_calls]
        self.assertLess(methods.index("starttls"), methods.index("login"))
        self.assertLess(methods.index("login"), methods.index("send_message"))

    def test_relative_password_file(self):
        filename = self.temp_file("secret\n")
        self.begin(self.auth(**{
            "smtp-username": "sender", "smtp-password-file": os.path.basename(filename), "exec_cwd": os.path.dirname(filename),
        }))
        self.smtp.login.assert_called_once_with("sender", "secret")

    def test_delivery_errors_are_redacted(self):
        errors = (
            ssl.SSLCertVerificationError("sensitive details"), smtplib.SMTPNotSupportedError("sensitive details"),
            smtplib.SMTPAuthenticationError(535, b"sensitive details"), TimeoutError("sensitive details"),
            smtplib.SMTPRecipientsRefused({"alice@example.com": "sensitive details"}),
        )
        for i, error in enumerate(errors):
            with self.subTest(error=type(error)):
                self.smtp.send_message.side_effect = error
                auth = self.auth(address=f"user{i}@example.com")
                with self.assertRaisesRegex(ValueError, "^cannot issue email authentication challenge$"):
                    self.begin(auth)
                self.assertEqual(auth.code, "")
                self.assertIsNone(auth.salt)
                self.assertFalse(auth.passed)

    def test_starttls_failure_never_sends(self):
        self.smtp.starttls.side_effect = smtplib.SMTPNotSupportedError("no TLS")
        with self.assertRaises(ValueError):
            self.begin(self.auth())
        self.smtp.send_message.assert_not_called()

    def test_refused_recipient_result(self):
        self.smtp.send_message.return_value = {"alice@example.com": (550, b"refused")}
        auth = self.auth()
        with self.assertRaises(ValueError):
            self.begin(auth)
        self.assertEqual(auth.code, "")

    def test_failed_delivery_after_address_prompt(self):
        auth = self.auth(mode="prompt", address="")
        self.begin(auth)
        self.smtp.send_message.side_effect = OSError("unavailable")
        self.assertFalse(auth.authenticate(self.response(auth, "bob@example.com")))
        self.assertFalse(auth.passed)
        self.assertEqual(auth.get_next_challenge(), ())

    def test_missing_password_file(self):
        auth = self.auth(**{"smtp-username": "sender", "smtp-password-file": "/nonexistent/email-auth-password"})
        with self.assertRaises(ValueError):
            self.begin(auth)
        self.smtp.send_message.assert_not_called()

    def test_recipient_cooldown_counts_failed_deliveries(self):
        self.smtp.send_message.side_effect = OSError("failed")
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.begin(self.auth())
        self.assertEqual(self.smtp.send_message.call_count, 1)

    def test_recipient_cooldown_boundary(self):
        first = self.auth()
        second = self.auth()
        third = self.auth()
        with patch("xpra.auth.code_base.monotonic", return_value=1000):
            first.reserve_send("Alice@EXAMPLE.COM")
        with patch("xpra.auth.code_base.monotonic", return_value=1059.999), self.assertRaises(ValueError):
            second.reserve_send("alice@example.com")
        with patch("xpra.auth.code_base.monotonic", return_value=1060):
            third.reserve_send("alice@example.com")

    def test_peer_limit_and_expiry(self):
        with patch("xpra.auth.code_base.monotonic", return_value=1000):
            for i in range(5):
                self.auth().reserve_send(f"user{i}@example.com")
            with self.assertRaises(ValueError):
                self.auth().reserve_send("sixth@example.com")
        with patch("xpra.auth.code_base.monotonic", return_value=1300):
            self.auth().reserve_send("sixth@example.com")

    def test_mapped_ipv6_uses_same_peer_limit(self):
        for i in range(5):
            self.auth().reserve_send(f"user{i}@example.com")
        auth = self.auth(connection=SimpleNamespace(remote=("::ffff:192.0.2.1", 1)))
        with self.assertRaises(ValueError):
            auth.reserve_send("sixth@example.com")

    def test_concurrent_recipient_reservations(self):
        gate = Event()

        def reserve(_index):
            auth = self.auth()
            gate.wait()
            try:
                auth.reserve_send("same@example.com")
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            attempts = [pool.submit(reserve, i) for i in range(8)]
            gate.set()
            self.assertEqual(sum(attempt.result() for attempt in attempts), 1)

    def test_tracking_limit_does_not_evict_live_entries(self):
        auth = self.auth(connection=None)
        with patch.object(Authenticator, "MAX_SEND_KEYS", 2):
            auth.reserve_send("one@example.com")
            auth.reserve_send("two@example.com")
            with self.assertRaises(ValueError):
                auth.reserve_send("three@example.com")
            self.assertEqual(len(auth.SENDS), 2)
            self.assertIn(("recipient", "one@example.com"), auth.SENDS)

    def test_exec_resolution(self):
        with patch("xpra.auth.code_base.lookup_command", return_value="bob@example.com") as lookup:
            auth = self.auth(mode="lookup", lookup="exec", command="/helper --email", remote={"username": "bob"})
            self.begin(auth)
            lookup.assert_called_once_with(["/helper", "--email"], "bob", 10)
            self.assertEqual(self.message()["To"], "bob@example.com")

    def test_lookup_failure_never_falls_back(self):
        with patch("xpra.auth.code_base.lookup_command", side_effect=ValueError("failed")):
            auth = self.auth(mode="lookup", lookup="exec", command="/helper")
            with self.assertRaises(ValueError):
                self.begin(auth)
        self.smtp.send_message.assert_not_called()

    def test_sql_bound_parameter_and_cleanup(self):
        engine = MagicMock()
        result = engine.connect.return_value.__enter__.return_value.execute.return_value.__enter__.return_value
        result.fetchmany.return_value = [("bob@example.com",)]
        sqlalchemy = SimpleNamespace(create_engine=MagicMock(return_value=engine), text=MagicMock(return_value="query"))
        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}):
            auth = self.auth(mode="lookup", lookup="sql", uri="sqlite:///users.db", remote={"username": "a' OR 1=1 --"})
            self.begin(auth)
            sqlalchemy.create_engine.assert_called_once_with("sqlite:///users.db", hide_parameters=True)
            sqlalchemy.text.assert_called_once_with("SELECT email FROM users WHERE username=:username")
            engine.connect.return_value.__enter__.return_value.execute.assert_called_once_with("query", {"username": "a' OR 1=1 --"})
            engine.dispose.assert_called_once()

    @unittest.skipUnless(importlib.util.find_spec("sqlalchemy"), "optional sqlalchemy is not installed")
    def test_sql_real_database(self):
        from sqlalchemy import create_engine, text
        filename = self.temp_file("")
        uri = "sqlite:///" + filename
        engine = create_engine(uri)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (username TEXT, email TEXT)"))
            connection.execute(text("INSERT INTO users VALUES (:username, :email)"), {
                "username": "alice", "email": "alice@example.com",
            })
        engine.dispose()
        self.begin(self.auth(mode="lookup", lookup="sql", uri=uri))
        self.assertEqual(self.message()["To"], "alice@example.com")
        for username in ("missing", "' OR 1=1 --"):
            with self.subTest(username=username), self.assertRaises(ValueError):
                self.begin(self.auth(mode="lookup", lookup="sql", uri=uri, remote={"username": username}))

    def test_sql_invalid_results(self):
        for rows in ([], [("a@example.com",), ("b@example.com",)], [(None,)], [(1234,)], [("",)], [("a@example.com", "extra")]):
            with self.subTest(rows=rows):
                engine = MagicMock()
                result = engine.connect.return_value.__enter__.return_value.execute.return_value.__enter__.return_value
                result.fetchmany.return_value = rows
                sqlalchemy = SimpleNamespace(create_engine=lambda *a, **kw: engine, text=lambda query: query)
                with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}), self.assertRaises(ValueError):
                    self.begin(self.auth(mode="lookup", lookup="sql", uri="sqlite:///users.db"))
                engine.dispose.assert_called_once()
        self.smtp.send_message.assert_not_called()

    def test_actual_client_three_challenges(self):
        from xpra.auth.password import Authenticator as PasswordAuth
        password_auth = PasswordAuth(value="primary-secret", username="alice")
        email_auth = self.auth(mode="prompt", address="")
        answers = iter(("primary-secret", "bob@example.com", "000123"))
        prompts = []

        def prompt(value):
            prompts.append(value)
            return next(answers)

        captured, errors = [], []
        handler = Handler(challenge_prompt_function=prompt)
        client = make_challenge_client(handler, "alice", captured, errors)
        client.challenge_handlers = [Handler(challenge_prompt_function=prompt) for _ in range(3)]

        def exchange(auth, salt, digest, label):
            salt_digest = auth.choose_salt_digest(get_salt_digests())
            packet = Packet(CHALLENGE, salt, {}, digest, salt_digest, label)
            self.assertTrue(client.validate_challenge_packet(packet))
            client.do_process_challenge(packet)
            self.assertFalse(errors)
            response, client_salt = captured[-1]
            self.assertTrue(auth.authenticate(typedict({"challenge_response": response, "challenge_client_salt": client_salt})))

        salt, digest = password_auth.get_challenge(get_digests())
        exchange(password_auth, salt, digest, password_auth.prompt)
        self.assertTrue(password_auth.passed)
        self.smtp.send_message.assert_not_called()
        salt, digest = email_auth.get_challenge(get_digests())
        exchange(email_auth, salt, digest, email_auth.prompt)
        self.assertFalse(email_auth.passed)
        exchange(email_auth, *email_auth.get_next_challenge())
        self.assertTrue(email_auth.passed)
        self.assertEqual(len(prompts), 3)
        self.assertEqual(len(captured), 3)
        self.assertEqual(client.challenge_handlers, [])

    def manager_flow(self, password="primary-secret", code="000123"):
        from xpra.server.auth import AuthenticationManager, get_auth_modules
        server = MagicMock()
        server.subsystems = {"network": MagicMock()}
        manager = AuthenticationManager(server)
        manager.auth_classes["ssl"] = get_auth_modules("ssl", (
            "password(value=primary-secret,username=alice)",
            "email(mode=prompt,smtp-host=smtp.example.com,from=xpra@example.com)",
        ))
        proto = MagicMock()
        proto._conn = SimpleNamespace(socktype="ssl", socktype_wrapped="ssl", options={}, remote=("192.0.2.1", 1))
        proto.is_closed.return_value = False
        proto.authenticators = ()
        packets = []
        proto.send_now.side_effect = packets.append
        caps = typedict({"username": "alice", "digest": get_digests(), "salt-digest": get_salt_digests()})
        answers = iter((password, "bob@example.com", code))

        def prompt(_label):
            return next(answers)

        captured, errors = [], []
        client = make_challenge_client(Handler(challenge_prompt_function=prompt), "alice", captured, errors)
        client.challenge_handlers = [Handler(challenge_prompt_function=prompt) for _ in range(3)]
        states = []
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
                states.append((tuple(auth.passed for auth in proto.authenticators), self.smtp.send_message.call_count))
            for auth in proto.authenticators:
                self.addCleanup(auth.cleanup)
            return accepted.call_count, failed.call_count, states

    def test_manager_waits_for_code_before_accepting(self):
        accepted, failed, states = self.manager_flow()
        self.assertEqual((accepted, failed), (1, 0))
        self.assertEqual(states, [((True, False), 0), ((True, False), 1), ((True, True), 1)])

    def test_manager_rejects_bad_code(self):
        accepted, failed, states = self.manager_flow(code="wrong")
        self.assertEqual((accepted, failed), (0, 1))
        self.assertEqual(states[-1], ((True, False), 1))

    def test_manager_does_not_send_before_primary_passes(self):
        accepted, failed, states = self.manager_flow(password="wrong")
        self.assertEqual((accepted, failed), (0, 1))
        self.assertEqual(states, [((False, False), 0)])

    def test_module_options_are_consumed(self):
        from xpra.auth.auth_helper import get_auth_module
        from xpra.auth.option import AUTH_OPTION_KEYS
        _name, _module, cls, options = get_auth_module(
            "email(mode=derived,address=@example.com,smtp-host=localhost,from=xpra@example.com,smtp-ssl-check-hostname=no)"
        )
        options[AUTH_OPTION_KEYS] = tuple(key for key in options if key != "exec_cwd")
        with patch("xpra.auth.option.log") as log:
            auth = cls(username="alice", **options)
            self.addCleanup(auth.cleanup)
            log.warn.assert_not_called()


class EmailCommandTest(unittest.TestCase):

    def run_helper(self, script, username="alice", timeout=5):
        return lookup_command([sys.executable, "-c", script], username, timeout)

    def test_single_username_argument(self):
        value = self.run_helper("import sys; print(sys.argv[1] + '@example.com')", "a; touch /tmp/unwanted")
        self.assertEqual(value, "a; touch /tmp/unwanted@example.com")

    def test_output_line_terminator(self):
        self.assertEqual(self.run_helper("print('alice@example.com')"), "alice@example.com")

    def test_command_failures(self):
        scripts = ("raise SystemExit(1)", "print('x' * 4097)", "import os; os.write(1, b'x' * 1000000)")
        for script in scripts:
            with self.subTest(script=script), self.assertRaises(ValueError):
                self.run_helper(script)

    def test_hung_helper_is_killed_and_reaped(self):
        for script in ("import time; time.sleep(10)", "import os, time; os.close(1); time.sleep(10)"):
            with self.subTest(script=script), self.assertRaises((ValueError, TimeoutError)):
                self.run_helper(script, timeout=0.1)

    def test_invalid_command_output(self):
        for script in ("print('a@example.com\\nb@example.com')", "print('a@example.com\\n')", "print('')"):
            with self.subTest(script=script), self.assertRaises(ValueError):
                validate_address(self.run_helper(script))
        with self.assertRaises(UnicodeDecodeError):
            self.run_helper("import os; os.write(1, b'\\xff')")

    def test_missing_executable(self):
        with self.assertRaises(OSError):
            lookup_command(["/nonexistent/email-lookup"], "alice", 1)

    def test_config_command_quoting(self):
        command = shlex.join([sys.executable, "-c", "print('alice@example.com')"])
        auth = Authenticator(mode="lookup", lookup="exec", command=command, **{
            "smtp-host": "localhost", "from": "xpra@example.com", "username": "alice",
        })
        self.assertEqual(auth.resolve_address(), "alice@example.com")


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed to generate test certificates")
class EmailSSLContextTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory(prefix="xpra-email-ssl-")
        cls.addClassCleanup(cls.tempdir.cleanup)
        cls.cert = os.path.join(cls.tempdir.name, "cert.pem")
        cls.key = os.path.join(cls.tempdir.name, "key.pem")
        subprocess.run([
            shutil.which("openssl"), "req", "-new", "-x509", "-days", "1", "-nodes", "-newkey", "rsa:2048",
            "-keyout", cls.key, "-out", cls.cert, "-subj", "/CN=smtp.example.com",
            "-addext", "subjectAltName=DNS:smtp.example.com", "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        with open(cls.cert, encoding="ascii") as cert_file:
            cls.pem = cert_file.read()

    def auth(self, **kwargs):
        auth = Authenticator(**{
            "username": "alice", "address": "alice@example.com", "smtp-host": "smtp.example.com", "from": "xpra@example.com",
            **kwargs,
        })
        self.addCleanup(auth.cleanup)
        return auth

    def handshake(self, context, hostname="smtp.example.com", client_cert=False):
        # MemoryBIO exercises OpenSSL certificate verification without opening sockets.
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert, self.key)
        if client_cert:
            server_context.verify_mode = ssl.CERT_REQUIRED
            server_context.load_verify_locations(cafile=self.cert)
        server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
        server = server_context.wrap_bio(server_in, server_out, server_side=True)
        client = context.wrap_bio(client_in, client_out, server_side=False, server_hostname=hostname)
        complete = set()
        for _ in range(100):
            for endpoint in (client, server):
                try:
                    endpoint.do_handshake()
                    complete.add(endpoint)
                except ssl.SSLWantReadError:
                    pass
            if len(complete) == 2:
                return
            server_in.write(client_out.read())
            client_in.write(server_out.read())
        self.fail("TLS handshake did not complete")

    def test_self_signed_certificate(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(self.auth().make_ssl_context())
        context = self.auth(**{"smtp-ssl-ca-certs": self.cert}).make_ssl_context()
        self.handshake(context)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(context, hostname="other.example.com")
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(self.auth().make_ssl_context())

    def test_relative_ca_path(self):
        context = self.auth(**{"smtp-ssl-ca-certs": "cert.pem", "exec_cwd": self.tempdir.name}).make_ssl_context()
        self.handshake(context)

    def test_ca_directory(self):
        with tempfile.TemporaryDirectory(prefix="xpra-email-ca-") as directory:
            # name the file after its subject hash ourselves: LibreSSL has no `openssl rehash`
            proc = subprocess.run([shutil.which("openssl"), "x509", "-hash", "-noout", "-in", self.cert],
                                  check=True, capture_output=True, text=True)
            shutil.copy(self.cert, os.path.join(directory, proc.stdout.strip() + ".0"))
            self.handshake(self.auth(**{"smtp-ssl-ca-certs": directory}).make_ssl_context())

    def test_inline_ca_data(self):
        der = ssl.PEM_cert_to_DER_cert(self.pem)
        for data in (self.pem, base64.b64encode(der).decode("ascii"), der.hex()):
            with self.subTest(encoding=data[:20]):
                self.handshake(self.auth(**{"smtp-ssl-ca-data": data}).make_ssl_context())

    def test_client_certificate(self):
        context = self.auth(**{
            "smtp-ssl-ca-certs": "cert.pem", "smtp-ssl-cert": "cert.pem", "smtp-ssl-key": "key.pem", "exec_cwd": self.tempdir.name,
        }).make_ssl_context()
        self.handshake(context, client_cert=True)

    def test_encrypted_client_key(self):
        with tempfile.TemporaryDirectory(prefix="xpra-email-key-") as directory:
            encrypted_key = os.path.join(directory, "key.pem")
            subprocess.run([
                shutil.which("openssl"), "pkey", "-in", self.key, "-out", encrypted_key, "-aes256", "-passout", "pass:test-password",
            ], check=True, capture_output=True)
            with open(os.path.join(directory, "password"), "w", encoding="utf-8") as password_file:
                password_file.write("test-password\n")
            options = {"smtp-ssl-ca-certs": self.cert, "smtp-ssl-cert": self.cert, "smtp-ssl-key": "key.pem", "exec_cwd": directory}
            with self.assertRaises(ssl.SSLError):
                self.auth(**options).make_ssl_context()
            context = self.auth(**options, **{"smtp-ssl-key-password-file": "password"}).make_ssl_context()
            self.handshake(context, client_cert=True)

    def test_hostname_check_can_be_disabled_while_verifying_certificate(self):
        context = self.auth(**{"smtp-ssl-ca-certs": self.cert, "smtp-ssl-check-hostname": "no"}).make_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.handshake(context, hostname="other.example.com")

    def test_explicitly_disabled_verification(self):
        context = self.auth(**{"smtp-ssl-server-verify-mode": "none"}).make_ssl_context()
        self.handshake(context)

    def test_explicit_protocol_retains_verification(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            context = self.auth(**{"smtp-ssl-protocol": "TLSv1_2", "smtp-ssl-ca-certs": self.cert}).make_ssl_context()
        self.assertEqual(context.protocol, ssl.PROTOCOL_TLSv1_2)
        self.assertEqual(context.verify_flags, ssl.create_default_context().verify_flags)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.handshake(context)


if __name__ == "__main__":
    unittest.main()
