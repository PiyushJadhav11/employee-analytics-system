"""Authorization primitives. UI visibility is never treated as the only boundary."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from hr_analytics.auth import Principal, AuthManager


class AuthorizationError(PermissionError):
    pass


class AuthorizationManager:
    def __init__(self, auth: AuthManager | None = None):
        self.auth = auth or AuthManager()

    def has_permission(self, principal: Principal, permission: str) -> bool:
        return permission in principal.permissions

    def require_permission(self, principal: Principal, permission: str) -> None:
        if not self.has_permission(principal, permission):
            self.auth.audit(principal.user_id, "AUTHORIZATION_DENIED", "DENIED", "permission", permission)
            raise AuthorizationError("You do not have permission to perform this action.")

    def may_access_department(self, principal: Principal, department_id: int) -> bool:
        if "employee.view_all" in principal.permissions or "analytics.view_all" in principal.permissions:
            return True
        return int(department_id) in principal.department_ids

    def require_department(self, principal: Principal, department_id: int, manage: bool = False) -> None:
        allowed = principal.manageable_department_ids if manage else principal.department_ids
        if not ("employee.view_all" in principal.permissions or "analytics.view_all" in principal.permissions) and int(department_id) not in allowed:
            self.auth.audit(principal.user_id, "AUTHORIZATION_DENIED", "DENIED", "department", str(department_id))
            raise AuthorizationError("You do not have access to this department.")

    def require_employee(self, principal: Principal, employee_id: int, write: bool = False) -> None:
        if "employee.view_all" in principal.permissions:
            return
        if "employee.view_self" in principal.permissions and principal.employee_id == int(employee_id):
            return
        row = self.auth.fetch_one("SELECT department_id FROM hr_oltp.employees WHERE employee_id=%s", (employee_id,))
        if row and int(row["department_id"]) in principal.department_ids:
            if not write or int(row["department_id"]) in principal.manageable_department_ids:
                return
        self.auth.audit(principal.user_id, "AUTHORIZATION_DENIED", "DENIED", "employee", str(employee_id))
        raise AuthorizationError("You do not have access to this employee.")

    def require_project(self, principal: Principal, project_id: int, manage: bool = False) -> None:
        row = self.auth.fetch_one("SELECT department_id FROM hr_oltp.projects WHERE project_id=%s", (project_id,))
        if row:
            self.require_department(principal, int(row["department_id"]), manage=manage)
            return
        raise AuthorizationError("You do not have access to this project.")
