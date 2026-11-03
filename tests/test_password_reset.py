import re
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

from app import app, get_db


class PasswordResetTest(unittest.TestCase):
    email = "codex.reset.test@local.invalid"
    username = "codex_reset_test"

    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.cleanup_user()
        with get_db() as db:
            db.execute(
                "INSERT INTO public.users(name,email,username,password_hash) VALUES(%s,%s,%s,%s)",
                ("Prueba Recuperación", self.email, self.username, generate_password_hash("Original123!")),
            )

    def tearDown(self):
        self.cleanup_user()

    def cleanup_user(self):
        with get_db() as db:
            db.execute("DELETE FROM public.users WHERE email=%s", (self.email,))

    @patch("app.send_password_reset")
    def test_complete_password_reset_flow(self, send_mail):
        response = self.client.post("/recover", data={"email": self.email})
        self.assertEqual(response.status_code, 302)
        send_mail.assert_called_once()
        reset_url = send_mail.call_args.args[1]
        token = re.search(r"/reset-password/([^/]+)$", reset_url).group(1)

        with get_db() as db:
            stored = db.execute(
                "SELECT token_hash,used_at FROM public.password_reset_tokens t JOIN public.users u ON u.id=t.user_id WHERE u.email=%s",
                (self.email,),
            ).fetchone()
        self.assertIsNotNone(stored)
        self.assertNotEqual(stored["token_hash"], token)
        self.assertIsNone(stored["used_at"])
        self.assertEqual(self.client.get(f"/reset-password/{token}").status_code, 200)

        response = self.client.post(
            f"/reset-password/{token}",
            data={"password": "NuevaSegura123!", "confirmation": "NuevaSegura123!"},
        )
        self.assertEqual(response.status_code, 302)
        with get_db() as db:
            user = db.execute("SELECT password_hash FROM public.users WHERE email=%s", (self.email,)).fetchone()
            used = db.execute("SELECT used_at FROM public.password_reset_tokens WHERE token_hash=%s", (stored["token_hash"],)).fetchone()
        self.assertTrue(check_password_hash(user["password_hash"], "NuevaSegura123!"))
        self.assertIsNotNone(used["used_at"])
        self.assertIn("inválido", self.client.get(f"/reset-password/{token}").get_data(as_text=True))

    @patch("app.send_password_reset")
    def test_unknown_email_keeps_neutral_response(self, send_mail):
        response = self.client.post("/recover", data={"email": "unknown@local.invalid"})
        self.assertEqual(response.status_code, 302)
        send_mail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
