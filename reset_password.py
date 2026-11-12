"""
Reset a SaliBot account password (for the person running the server).

Usage:
    python reset_password.py

You'll be asked for the email and the new password. The password is typed
hidden and is only stored as a secure hash, never as plain text.
"""

from getpass import getpass

from database import SessionLocal, User, LoginSession, hash_password, init_db


def main():
    init_db()
    email = input("Account email: ").strip().lower()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print("No account found with that email.")
            return

        password = getpass("New password (at least 8 characters, hidden): ")
        if len(password) < 8:
            print("Password must be at least 8 characters. Nothing changed.")
            return
        if getpass("Type it again: ") != password:
            print("The passwords didn't match. Nothing changed.")
            return

        user.password_hash = hash_password(password)
        # Log out everywhere, so only the new password works
        db.query(LoginSession).filter(LoginSession.user_id == user.id).delete()
        db.commit()
        print(f"Password updated for {user.name}. You can now log in with the new password.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
