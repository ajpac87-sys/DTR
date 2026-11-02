"""
Who is signed in, what their job lets them do, and which company's records
they can reach.

One fleet never sees another fleet's records. Two things make that hold:

1. A person's company is read from their signed sign-in token, and from
   nothing else: never from a web address, a form, or a header the browser
   chose.
2. Every read of company records is filtered by `company_filter()`. If it
   can't tell who is asking, it returns NOTHING, a filter no record matches.
   A mistake shows up as an empty screen, never as another company's data.

Plain Python on purpose (no web or database code), so the rules can be
tested on their own.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    MECHANIC = "mechanic"
    SHOP_MANAGER = "shop_manager"
    FLEET_MANAGER = "fleet_manager"
    ADMIN = "admin"                          # runs one customer company
    PLATFORM_OPERATOR = "platform_operator"  # Apex staff, across companies


# --- What each job can do ----------------------------------------------------
# The server checks these on every change. The screens only hide buttons.

EDIT_UNITS = "edit_units"
IMPORT_UNITS = "import_units"
MANAGE_PEOPLE = "manage_people"
READ_AUDIT = "read_audit"

PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.MECHANIC: frozenset(),
    Role.SHOP_MANAGER: frozenset({EDIT_UNITS, MANAGE_PEOPLE}),
    Role.FLEET_MANAGER: frozenset({EDIT_UNITS, IMPORT_UNITS, MANAGE_PEOPLE}),
    Role.ADMIN: frozenset({EDIT_UNITS, IMPORT_UNITS, MANAGE_PEOPLE,
                           READ_AUDIT}),
    Role.PLATFORM_OPERATOR: frozenset(),
}

# Who can add whom. Each job adds its own kind and the jobs under it in its
# own department, never a job above it. The shop runs the shop, the office
# runs the office, the admin runs both.
CAN_ADD: dict[Role, frozenset[Role]] = {
    Role.MECHANIC: frozenset(),
    Role.SHOP_MANAGER: frozenset({Role.MECHANIC, Role.SHOP_MANAGER}),
    Role.FLEET_MANAGER: frozenset({Role.FLEET_MANAGER}),
    Role.ADMIN: frozenset({Role.MECHANIC, Role.SHOP_MANAGER,
                           Role.FLEET_MANAGER, Role.ADMIN}),
    # Apex creates a company's first admin from its console and stops there.
    Role.PLATFORM_OPERATOR: frozenset(),
}


def can_grant(by: Role, new_role: Role) -> bool:
    return new_role in CAN_ADD.get(by, frozenset())


# --- The signed-in person ------------------------------------------------------

@dataclass(frozen=True)
class Person:
    """Built only from a verified sign-in token."""
    user_id: str
    org_id: str | None
    role: Role
    name: str = ""

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("a signed-in person needs a user id")
        if not isinstance(self.role, Role):
            raise TypeError("role must be a Role")
        operator = self.role is Role.PLATFORM_OPERATOR
        # Apex staff belong to no customer company; everyone else to exactly one.
        if operator and self.org_id:
            raise ValueError("Apex staff have no home company")
        if not operator and not self.org_id:
            raise ValueError(f"a {self.role.value} must belong to a company")

    @property
    def is_operator(self) -> bool:
        return self.role is Role.PLATFORM_OPERATOR

    def may(self, permission: str) -> bool:
        return permission in PERMISSIONS[self.role]


# --- Which records a person can reach -----------------------------------------

NOTHING: dict = {"org_id": {"$in": []}}     # matches no record, ever


def company_filter(person: Person | None) -> dict:
    """The database filter that keeps a person inside their own company."""
    if person is None:
        return dict(NOTHING)
    if person.is_operator:
        return {}                       # Apex reads across companies
    return {"org_id": person.org_id} if person.org_id else dict(NOTHING)


def within_company(person: Person | None, condition: dict | None = None) -> dict:
    """
    A caller's own condition, kept inside the person's company. The two are
    combined with $and, so a condition can narrow the result but never widen
    it: asking for another company's org_id just returns nothing.
    """
    wall = company_filter(person)
    if wall == NOTHING:
        return dict(NOTHING)
    parts = [c for c in (wall, condition) if c]
    if not parts:
        return {}
    return dict(parts[0]) if len(parts) == 1 else {"$and": parts}
