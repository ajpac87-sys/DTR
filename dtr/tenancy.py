"""
Who is asking, what they may do, and which company's records they may touch.

THE RULE: one fleet never sees another fleet's records. Ever.

How that is made hard to get wrong:
  - The company a person belongs to comes ONLY from their verified login
    token. Never from a web address, a form field, or anything the browser
    sends.
  - Every read of company data goes through `scope_filter()`. When it cannot
    establish who is asking, it returns DENY_ALL, which matches nothing. A
    caller who forgets something gets nothing, not everything.

No web framework or database here on purpose, so these rules can be tested
directly. Carried over from InMotion's tenancy.py, trimmed to what a shop needs.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Role(str, Enum):
    MECHANIC = "mechanic"
    SHOP_MANAGER = "shop_manager"
    FLEET_MANAGER = "fleet_manager"
    # Administrator of ONE customer company. Sees every department in it.
    ADMIN = "admin"
    # Apex staff. The only role that sees across companies, and it has no
    # home company. Never overload ADMIN to mean this.
    PLATFORM_OPERATOR = "platform_operator"


LABEL = {
    Role.MECHANIC: "Mechanic",
    Role.SHOP_MANAGER: "Shop manager",
    Role.FLEET_MANAGER: "Fleet manager",
    Role.ADMIN: "Company admin",
    Role.PLATFORM_OPERATOR: "Platform operator (Apex)",
}

# Which roles each role may give to someone else in its own company.
# Nobody can hand out a role above their own; that would be a documented way
# around the permission system.
GRANTABLE: dict[Role, frozenset[Role]] = {
    Role.ADMIN: frozenset({Role.MECHANIC, Role.SHOP_MANAGER,
                           Role.FLEET_MANAGER, Role.ADMIN}),
    Role.FLEET_MANAGER: frozenset({Role.FLEET_MANAGER}),
    Role.SHOP_MANAGER: frozenset({Role.MECHANIC, Role.SHOP_MANAGER}),
    Role.MECHANIC: frozenset(),
    # Apex sets up a company's first admin through its own console route; it
    # does not hand out roles inside a customer's company.
    Role.PLATFORM_OPERATOR: frozenset(),
}


def can_grant(actor: Role, target: Role) -> bool:
    return target in GRANTABLE.get(actor, frozenset())


# What each role may do. Checked on the server for every change; the screens
# only hide buttons as a convenience.
EDIT_UNITS = "edit_units"          # add / change trucks and trailers
IMPORT_UNITS = "import_units"      # load the fleet list from a spreadsheet
MANAGE_PEOPLE = "manage_people"    # add users to the company
READ_AUDIT = "read_audit"          # read the company's change log

PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ADMIN: frozenset({EDIT_UNITS, IMPORT_UNITS, MANAGE_PEOPLE,
                           READ_AUDIT}),
    Role.FLEET_MANAGER: frozenset({EDIT_UNITS, IMPORT_UNITS, MANAGE_PEOPLE}),
    Role.SHOP_MANAGER: frozenset({EDIT_UNITS, MANAGE_PEOPLE}),
    Role.MECHANIC: frozenset(),
    Role.PLATFORM_OPERATOR: frozenset(),
}


@dataclass(frozen=True)
class Principal:
    """
    A signed-in person. Built only from a verified token; this is where trust
    begins.
    """
    user_id: str
    org_id: str | None
    role: Role
    name: str = ""

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("a principal needs a user_id")
        if not isinstance(self.role, Role):
            raise TypeError("role must be a Role")
        if self.role is Role.PLATFORM_OPERATOR:
            # A platform operator with a home company would be half-scoped.
            # Refuse the combination outright.
            if self.org_id:
                raise ValueError("a platform operator has no home company")
        elif not self.org_id:
            raise ValueError(f"role {self.role.value} needs a company")

    @property
    def is_operator(self) -> bool:
        return self.role is Role.PLATFORM_OPERATOR

    def may(self, permission: str) -> bool:
        return permission in PERMISSIONS.get(self.role, frozenset())


# Matches no record. The deny-by-default answer.
DENY_ALL: dict[str, Any] = {"_deny": {"$exists": True, "$eq": "__never__"}}


def scope_filter(principal: Principal | None) -> dict[str, Any]:
    """
    THE one place a read is limited to a company.

    No principal: nothing. Apex operator: every company (standing access under
    the service agreement). Anyone else: their own company only.
    """
    if principal is None:
        return dict(DENY_ALL)
    if principal.is_operator:
        return {}
    if not principal.org_id:
        return dict(DENY_ALL)
    return {"org_id": principal.org_id}


def scoped(principal: Principal | None, condition: dict[str, Any] | None = None
           ) -> dict[str, Any]:
    """
    Combine the company scope with a caller's own condition.

    Joined with $and, so a condition can only NARROW the result. Asking for
    {"org_id": "someone_else"} returns nothing rather than another company.
    """
    base = scope_filter(principal)
    if base == DENY_ALL:
        return dict(DENY_ALL)
    parts = [c for c in (base, condition or {}) if c]
    if not parts:
        return {}
    if len(parts) == 1:
        return dict(parts[0])
    return {"$and": parts}
