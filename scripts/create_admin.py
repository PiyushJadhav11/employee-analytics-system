"""Create the first SYSTEM_ADMIN account. Run once from the project root."""
from getpass import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hr_analytics.auth import AuthManager, normalize_email, validate_password


def main():
    auth = AuthManager()
    existing = auth.fetch_one("""SELECT COUNT(*) AS n FROM hr_oltp.users u
        JOIN hr_oltp.user_roles ur USING(user_id) JOIN hr_oltp.roles r USING(role_id)
        WHERE r.role_name='SYSTEM_ADMIN' AND u.is_active=TRUE""")
    if existing and int(existing['n']) > 0:
        print("An active System Admin already exists. Use Security administration to create additional accounts.")
        return 1
    email = normalize_email(input("Admin email: "))
    name = input("Admin display name: ").strip()
    p1 = getpass("Admin passphrase (12+ characters): ")
    p2 = getpass("Confirm passphrase: ")
    if p1 != p2:
        print("Passphrases do not match.")
        return 1
    validate_password(p1)
    uid = auth.create_user(email, name, p1, "SYSTEM_ADMIN")
    print(f"Created initial System Admin (user_id={uid}). Keep this account private.")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
