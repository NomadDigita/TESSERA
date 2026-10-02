import unittest

from tessera.auth import AuthError, AuthManager, hash_password, verify_password
from tessera.storage import SQLiteStore


class AuthTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verifiable(self):
        first = hash_password("a-secure-password")
        second = hash_password("a-secure-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("a-secure-password", first))
        self.assertFalse(verify_password("wrong-password", first))
        self.assertNotIn("a-secure-password", first)

    def test_login_issues_verifiable_expiring_token(self):
        clock = [1000]
        store = SQLiteStore()
        auth = AuthManager(store, "x" * 32, ttl_seconds=300, clock=lambda: clock[0])
        auth.create_user("Alice", "a-secure-password", "operator")
        token = auth.login("alice", "a-secure-password")["access_token"]
        self.assertEqual(auth.verify(token), {"username": "alice", "role": "operator"})
        clock[0] = 1301
        with self.assertRaises(AuthError):
            auth.verify(token)

    def test_role_hierarchy_is_enforced(self):
        AuthManager.require({"role": "operator"}, "researcher")
        with self.assertRaises(AuthError):
            AuthManager.require({"role": "viewer"}, "operator")

    def test_permission_change_invalidates_existing_token(self):
        store = SQLiteStore()
        auth = AuthManager(store, "x" * 32)
        auth.create_user("alice", "a-secure-password", "viewer")
        token = auth.login("alice", "a-secure-password")["access_token"]
        with store._db:
            store._db.execute("UPDATE users SET role='operator' WHERE username='alice'")
        with self.assertRaises(AuthError):
            auth.verify(token)


if __name__ == "__main__":
    unittest.main()
