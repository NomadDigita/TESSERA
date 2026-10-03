import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib import error, request


class HTTPAuthTests(unittest.TestCase):
    def setUp(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self.port = listener.getsockname()[1]
        listener.close()
        self.temp = tempfile.TemporaryDirectory()
        env = os.environ.copy()
        env.update({
            "TESSERA_HOST": "127.0.0.1", "TESSERA_PORT": str(self.port),
            "TESSERA_DATABASE_PATH": str(Path(self.temp.name) / "http.db"),
            "TESSERA_ARTIFACT_PATH": str(Path(self.temp.name) / "artifacts"),
            "TESSERA_AUTH_ENABLED": "true", "TESSERA_SESSION_SECRET": "s" * 40,
            "TESSERA_ADMIN_USERNAME": "admin", "TESSERA_ADMIN_PASSWORD": "secure-admin-password",
            "TESSERA_LOGIN_RATE_LIMIT": "2", "TESSERA_API_RATE_LIMIT": "50",
        })
        self.process = subprocess.Popen([sys.executable, "-m", "tessera"], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=0.5)
                break
            except Exception:
                time.sleep(0.1)
        else:
            self.fail("TESSERA HTTP server did not start")

    def tearDown(self):
        self.process.terminate()
        self.process.wait(timeout=5)
        self.temp.cleanup()

    def call(self, path, method="GET", payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(f"http://127.0.0.1:{self.port}{path}", data=body,
                              headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=5) as response:
                return response.status, dict(response.headers), json.loads(response.read())
        except error.HTTPError as exc:
            return exc.code, dict(exc.headers), json.loads(exc.read())

    def test_rate_limit_admin_lifecycle_and_logout(self):
        for _ in range(2):
            status, _, _ = self.call("/api/auth/login", "POST",
                                     {"username": "attacker", "password": "incorrect-password"})
            self.assertEqual(status, 401)
        status, headers, payload = self.call("/api/auth/login", "POST",
                                             {"username": "attacker", "password": "incorrect-password"})
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", headers)
        self.assertEqual(payload["error"], "Rate limit exceeded")

        status, _, login = self.call("/api/auth/login", "POST",
                                     {"username": "admin", "password": "secure-admin-password"})
        self.assertEqual(status, 200)
        token = login["access_token"]
        status, _, created = self.call("/api/admin/users", "POST",
                                       {"username": "researcher", "password": "secure-user-password",
                                        "role": "researcher"}, token)
        self.assertEqual(status, 201)
        self.assertEqual(created["role"], "researcher")

        status, _, sessions = self.call("/api/auth/sessions", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(sessions["sessions"]), 1)
        status, _, _ = self.call("/api/auth/logout", "POST", {}, token)
        self.assertEqual(status, 200)
        status, _, payload = self.call("/api/portfolio", token=token)
        self.assertEqual(status, 401)
        self.assertIn("revoked", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()
