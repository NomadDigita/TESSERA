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
        principal = auth.verify(token)
        self.assertEqual(principal["username"], "alice")
        self.assertEqual(principal["role"], "operator")
        self.assertIn("jti", principal)
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

    def test_logout_revokes_session_before_expiry(self):
        store = SQLiteStore()
        auth = AuthManager(store, "x" * 32)
        auth.create_user("alice", "a-secure-password", "viewer")
        token = auth.login("alice", "a-secure-password")["access_token"]
        auth.logout(token)
        with self.assertRaisesRegex(AuthError, "revoked"):
            auth.verify(token)

    def test_admin_user_update_revokes_sessions(self):
        store = SQLiteStore()
        auth = AuthManager(store, "x" * 32)
        auth.create_user("admin", "a-secure-password", "admin")
        auth.create_user("alice", "another-secure-password", "viewer")
        token = auth.login("alice", "another-secure-password")["access_token"]
        updated = auth.update_user("alice", role="researcher")
        self.assertEqual(updated["role"], "researcher")
        with self.assertRaises(AuthError):
            auth.verify(token)

    def test_last_active_admin_cannot_be_removed(self):
        store = SQLiteStore()
        auth = AuthManager(store, "x" * 32)
        auth.create_user("admin", "a-secure-password", "admin")
        with self.assertRaisesRegex(ValueError, "last active"):
            auth.update_user("admin", active=False)

    def test_system_agent_role_cannot_be_assigned_to_human(self):
        store = SQLiteStore()
        auth = AuthManager(store, "x" * 32)
        with self.assertRaises(ValueError):
            auth.create_user("agent", "a-secure-password", "system_agent")


if __name__ == "__main__":
    unittest.main()
