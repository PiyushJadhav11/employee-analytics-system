"""Local password authentication, account provisioning and audit logging."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from hr_analytics.db_manager import DatabaseConnection, DatabaseError

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
BREACHED = {"password123456", "123456789012", "qwerty123456", "letmein123456"}
DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=2$Esa9dnF4aASYwl0X7wTxgA$9c8+20PctfnVZne4Jc0C0MPL+FA8yVZ7cyxVJm7qRJ4"


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    display_name: str
    employee_id: int | None
    roles: frozenset[str]
    permissions: frozenset[str]
    department_ids: frozenset[int]
    manageable_department_ids: frozenset[int]
    must_change_password: bool = False

    @property
    def is_employee(self) -> bool:
        return "EMPLOYEE" in self.roles and not bool(self.roles & {"SYSTEM_ADMIN", "HR_ADMIN", "HR_MANAGER", "DEPARTMENT_MANAGER"})


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > 150 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("Enter a valid email address.")
    return value


def validate_password(password: str) -> None:
    if len(password or "") < 12:
        raise ValueError("Use a passphrase with at least 12 characters.")
    if len(password) > 256:
        raise ValueError("Password is too long.")
    if password.lower() in BREACHED:
        raise ValueError("Choose a less common password.")


class AuthManager(DatabaseConnection):
    def hash_password(self, password: str) -> str:
        validate_password(password)
        return PASSWORDS.hash(password)

    @staticmethod
    def verify_password(password_hash: str | None, password: str) -> bool:
        if not password_hash:
            return False
        try:
            return PASSWORDS.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError):
            return False

    def audit(self, user_id: int | None, action: str, outcome: str,
              resource_type: str | None = None, resource_id: str | None = None,
              details: str | None = None, ip_address: str | None = None, cursor=None) -> None:
        # Use the caller's transaction when present so audit and security changes commit atomically.
        sql = """INSERT INTO hr_oltp.security_audit_log
                 (user_id, action, resource_type, resource_id, outcome, ip_address, details)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)"""
        params = (user_id, action[:80], resource_type, resource_id, outcome, ip_address, (details or "")[:500] or None)
        if cursor is not None:
            cursor.execute(sql, params)
            return
        try:
            self.execute(sql, params)
        except DatabaseError:
            import logging
            logging.getLogger(__name__).exception("Could not write security audit event")

    def authenticate(self, email: str, password: str) -> Principal | None:
        try:
            email = normalize_email(email)
        except ValueError:
            self.audit(None, "LOGIN_FAILURE", "FAILED", details="Invalid email format")
            return None
        now = datetime.now()
        with self.transaction() as cur:
            cur.execute("SELECT user_id, password_hash, is_active, failed_logins, locked_until, must_change_password FROM hr_oltp.users WHERE email=%s FOR UPDATE", (email,))
            user = cur.fetchone()
            if not user:
                # Same public result for unknown email and incorrect password.
                # Perform an Argon2 verification for unknown users too, reducing email-enumeration timing differences.
                self.verify_password(DUMMY_PASSWORD_HASH, password)
                self.audit(None, "LOGIN_FAILURE", "FAILED", details="Invalid credentials", cursor=cur)
                return None
            uid = int(user["user_id"])
            if not user["is_active"] or (user["locked_until"] and user["locked_until"] > now):
                self.audit(uid, "LOGIN_FAILURE", "FAILED", details="Inactive or locked account", cursor=cur)
                return None
            if not self.verify_password(user["password_hash"], password):
                failures = int(user["failed_logins"] or 0) + 1
                locked_until = now + timedelta(minutes=LOCK_MINUTES) if failures >= MAX_FAILED_LOGINS else None
                cur.execute("UPDATE hr_oltp.users SET failed_logins=%s, locked_until=%s WHERE user_id=%s",
                            (min(failures, 65535), locked_until, uid))
                self.audit(uid, "LOGIN_FAILURE", "FAILED", details="Invalid credentials", cursor=cur)
                return None
            cur.execute("UPDATE hr_oltp.users SET failed_logins=0, locked_until=NULL, last_login_at=NOW() WHERE user_id=%s", (uid,))
            self.audit(uid, "LOGIN_SUCCESS", "SUCCESS", resource_type="user", resource_id=str(uid), cursor=cur)
        return self.load_principal(uid)

    def load_principal(self, user_id: int) -> Principal | None:
        user = self.fetch_one("SELECT user_id,email,display_name,employee_id,is_active,must_change_password FROM hr_oltp.users WHERE user_id=%s", (user_id,))
        if not user or not user["is_active"]:
            return None
        roles = self.fetch_all(
            """SELECT r.role_name FROM hr_oltp.user_roles ur
               JOIN hr_oltp.roles r ON r.role_id=ur.role_id WHERE ur.user_id=%s""", (user_id,))
        permissions = self.fetch_all(
            """SELECT DISTINCT p.permission_key FROM hr_oltp.user_roles ur
               JOIN hr_oltp.role_permissions rp ON rp.role_id=ur.role_id
               JOIN hr_oltp.permissions p ON p.permission_id=rp.permission_id
               WHERE ur.user_id=%s""", (user_id,))
        departments = self.fetch_all(
            "SELECT department_id,can_manage FROM hr_oltp.user_departments WHERE user_id=%s", (user_id,))
        return Principal(
            user_id=int(user["user_id"]), email=user["email"], display_name=user["display_name"],
            employee_id=int(user["employee_id"]) if user["employee_id"] is not None else None,
            roles=frozenset(r["role_name"] for r in roles),
            permissions=frozenset(p["permission_key"] for p in permissions),
            department_ids=frozenset(int(d["department_id"]) for d in departments),
            manageable_department_ids=frozenset(int(d["department_id"]) for d in departments if d["can_manage"]),
            must_change_password=bool(user["must_change_password"]),
        )

    def register_employee(self, email: str, display_name: str, password: str) -> int:
        email = normalize_email(email)
        if not display_name or not display_name.strip():
            raise ValueError("Enter your display name.")
        password_hash = self.hash_password(password)
        with self.transaction() as cur:
            cur.execute("SELECT employee_id,first_name,last_name FROM hr_oltp.employees WHERE LOWER(email)=LOWER(%s)", (email,))
            employee = cur.fetchone()
            if not employee:
                raise ValueError("This email is not linked to an employee record. Contact HR.")
            cur.execute("SELECT user_id FROM hr_oltp.users WHERE email=%s", (email,))
            if cur.fetchone():
                raise ValueError("An account already exists for this email.")
            cur.execute("INSERT INTO hr_oltp.users(email,display_name,password_hash,employee_id) VALUES(%s,%s,%s,%s)",
                        (email, display_name.strip()[:125], password_hash, employee["employee_id"]))
            uid = int(cur.lastrowid)
            cur.execute("INSERT INTO hr_oltp.user_roles(user_id,role_id) SELECT %s,role_id FROM hr_oltp.roles WHERE role_name='EMPLOYEE'", (uid,))
            cur.execute("INSERT INTO hr_oltp.user_departments(user_id,department_id,can_manage) SELECT %s,department_id,FALSE FROM hr_oltp.employees WHERE employee_id=%s", (uid, employee["employee_id"]))
            self.audit(uid, "EMPLOYEE_SELF_REGISTRATION", "SUCCESS", "user", str(uid), cursor=cur)
        return uid

    def create_user(self, email: str, display_name: str, password: str, role_name: str,
                    employee_id: int | None = None, department_ids: Iterable[int] = (),
                    can_manage: bool = False, granted_by: int | None = None) -> int:
        email = normalize_email(email)
        if not display_name or not display_name.strip():
            raise ValueError("Enter a display name.")
        password_hash = self.hash_password(password)
        allowed_roles = {"SYSTEM_ADMIN", "HR_ADMIN", "HR_MANAGER", "DEPARTMENT_MANAGER", "EMPLOYEE"}
        if role_name not in allowed_roles:
            raise ValueError("Invalid role.")
        with self.transaction() as cur:
            cur.execute("SELECT user_id FROM hr_oltp.users WHERE email=%s", (email,))
            if cur.fetchone():
                raise ValueError("An account already exists for this email.")
            cur.execute("INSERT INTO hr_oltp.users(email,display_name,password_hash,employee_id) VALUES(%s,%s,%s,%s)",
                        (email, display_name.strip()[:125], password_hash, employee_id))
            uid = int(cur.lastrowid)
            cur.execute("SELECT role_id FROM hr_oltp.roles WHERE role_name=%s", (role_name,))
            role = cur.fetchone()
            if not role:
                raise ValueError("Role catalogue is missing. Run database setup first.")
            cur.execute("INSERT INTO hr_oltp.user_roles(user_id,role_id,granted_by) VALUES(%s,%s,%s)",
                        (uid, role["role_id"], granted_by))
            for dept_id in sorted(set(int(x) for x in department_ids)):
                cur.execute("INSERT INTO hr_oltp.user_departments(user_id,department_id,can_manage) VALUES(%s,%s,%s)",
                            (uid, dept_id, bool(can_manage)))
            # Admin-provisioned accounts receive a temporary password and must replace it at first login.
            cur.execute("UPDATE hr_oltp.users SET must_change_password=TRUE WHERE user_id=%s", (uid,))
            self.audit(granted_by, "USER_CREATE", "SUCCESS", "user", str(uid), f"role={role_name}", cursor=cur)
        return uid

    def set_user_active(self, user_id: int, active: bool, actor_id: int) -> None:
        with self.transaction() as cur:
            cur.execute("SELECT u.is_active, EXISTS(SELECT 1 FROM hr_oltp.user_roles ur JOIN hr_oltp.roles r USING(role_id) WHERE ur.user_id=u.user_id AND r.role_name='SYSTEM_ADMIN') AS is_admin FROM hr_oltp.users u WHERE u.user_id=%s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("User not found.")
            if not active and row["is_admin"]:
                cur.execute("SELECT COUNT(*) AS n FROM hr_oltp.users u JOIN hr_oltp.user_roles ur USING(user_id) JOIN hr_oltp.roles r USING(role_id) WHERE u.is_active=TRUE AND r.role_name='SYSTEM_ADMIN'")
                if int(cur.fetchone()["n"]) <= 1:
                    raise ValueError("Cannot deactivate the final active System Admin.")
            cur.execute("UPDATE hr_oltp.users SET is_active=%s WHERE user_id=%s", (bool(active), user_id))
            self.audit(actor_id, "USER_ACTIVATE" if active else "USER_DEACTIVATE", "SUCCESS", "user", str(user_id), cursor=cur)

    def grant_role(self, user_id: int, role_name: str, actor_id: int) -> None:
        with self.transaction() as cur:
            cur.execute("SELECT role_id FROM hr_oltp.roles WHERE role_name=%s", (role_name,))
            role = cur.fetchone()
            if not role:
                raise ValueError("Unknown role.")
            cur.execute("INSERT IGNORE INTO hr_oltp.user_roles(user_id,role_id,granted_by) VALUES(%s,%s,%s)",
                        (user_id, role["role_id"], actor_id))
            self.audit(actor_id, "ROLE_GRANT", "SUCCESS", "user", str(user_id), f"role={role_name}", cursor=cur)

    def revoke_role(self, user_id: int, role_name: str, actor_id: int) -> None:
        with self.transaction() as cur:
            cur.execute("SELECT role_id FROM hr_oltp.roles WHERE role_name=%s", (role_name,))
            role = cur.fetchone()
            if not role:
                raise ValueError("Unknown role.")
            if role_name == "SYSTEM_ADMIN":
                cur.execute("SELECT COUNT(*) AS n FROM hr_oltp.users u JOIN hr_oltp.user_roles ur USING(user_id) JOIN hr_oltp.roles r USING(role_id) WHERE u.is_active=TRUE AND r.role_name='SYSTEM_ADMIN'")
                if int(cur.fetchone()["n"]) <= 1:
                    raise ValueError("Cannot revoke the final active System Admin role.")
            cur.execute("DELETE FROM hr_oltp.user_roles WHERE user_id=%s AND role_id=%s", (user_id, role["role_id"]))
            self.audit(actor_id, "ROLE_REVOKE", "SUCCESS", "user", str(user_id), f"role={role_name}", cursor=cur)

    def revoke_department(self, user_id: int, department_id: int, actor_id: int) -> None:
        with self.transaction() as cur:
            cur.execute("DELETE FROM hr_oltp.user_departments WHERE user_id=%s AND department_id=%s", (user_id, department_id))
            self.audit(actor_id, "DEPARTMENT_REVOKE", "SUCCESS", "user", str(user_id), f"department_id={department_id}", cursor=cur)

    def verify_actor_password(self, actor_id: int, password: str) -> bool:
        row = self.fetch_one("SELECT password_hash FROM hr_oltp.users WHERE user_id=%s AND is_active=TRUE", (actor_id,))
        return bool(row and self.verify_password(row["password_hash"], password))

    def reset_password(self, user_id: int, password: str, actor_id: int) -> None:
        password_hash = self.hash_password(password)
        with self.transaction() as cur:
            cur.execute("UPDATE hr_oltp.users SET password_hash=%s,failed_logins=0,locked_until=NULL,must_change_password=TRUE WHERE user_id=%s", (password_hash, user_id))
            if cur.rowcount != 1:
                raise ValueError("User not found.")
            self.audit(actor_id, "PASSWORD_RESET", "SUCCESS", "user", str(user_id), cursor=cur)

    def assign_department(self, user_id: int, department_id: int, can_manage: bool, actor_id: int) -> None:
        with self.transaction() as cur:
            cur.execute("INSERT INTO hr_oltp.user_departments(user_id,department_id,can_manage) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE can_manage=VALUES(can_manage)",
                        (user_id, department_id, bool(can_manage)))
            self.audit(actor_id, "DEPARTMENT_GRANT", "SUCCESS", "user", str(user_id), f"department_id={department_id}; can_manage={bool(can_manage)}", cursor=cur)

    def change_own_password(self, user_id: int, current_password: str, new_password: str) -> None:
        new_hash = self.hash_password(new_password)
        with self.transaction() as cur:
            cur.execute("SELECT password_hash FROM hr_oltp.users WHERE user_id=%s AND is_active=TRUE FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row or not self.verify_password(row["password_hash"], current_password):
                raise ValueError("Current password is incorrect.")
            cur.execute("UPDATE hr_oltp.users SET password_hash=%s,must_change_password=FALSE,failed_logins=0,locked_until=NULL WHERE user_id=%s", (new_hash, user_id))
            self.audit(user_id, "PASSWORD_CHANGE", "SUCCESS", "user", str(user_id), cursor=cur)

    def users(self):
        return self.fetch_df("""SELECT u.user_id,u.email,u.display_name,u.employee_id,u.is_active,u.last_login_at,
            GROUP_CONCAT(DISTINCT r.role_name ORDER BY r.role_name SEPARATOR ', ') AS roles
            FROM hr_oltp.users u LEFT JOIN hr_oltp.user_roles ur USING(user_id)
            LEFT JOIN hr_oltp.roles r USING(role_id) GROUP BY u.user_id ORDER BY u.created_at DESC""")

    def audit_events(self, limit: int = 200):
        return self.fetch_df("""SELECT a.audit_id,a.created_at,u.email,a.action,a.resource_type,a.resource_id,
            a.outcome,a.details FROM hr_oltp.security_audit_log a LEFT JOIN hr_oltp.users u USING(user_id)
            ORDER BY a.created_at DESC LIMIT %s""", (int(limit),))
