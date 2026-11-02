"""
The regulatory register.

Every rule this code depends on, with its citation, what depends on it, and
when it was last checked against the official text. When a regulation
changes, this list says which part of the system to look at.

Official sources only (eCFR, FMCSA.gov, CA DMV/CHP, official state code).
An entry not yet checked by a person against the official text says so.
"""
from __future__ import annotations

REGISTER = [
    {
        "rule": "49 CFR 396.3(b)(1)",
        "source": "https://www.ecfr.gov/current/title-49/section-396.3",
        "as_understood": (
            "Per the project brief (NOT yet read by us against eCFR): keep, "
            "for each vehicle, identification: company number, make, serial "
            "number, year, and the owner's name if the carrier does not own "
            "it."),
        "depends": ["assets: unit_number, make, vin (serial), model_year, "
                    "owned_by_carrier / furnished_by"],
        "last_checked": None,
        "note": ("Brief written Nov 2, 2026 says Part 396 was amended in "
                 "2026 (incl. Jul 21, 91 FR 45662). Not yet re-read against "
                 "eCFR for DTR; check before relying on it."),
    },
    {
        "rule": "49 CFR 396.3(c)",
        "source": "https://www.ecfr.gov/current/title-49/section-396.3",
        "as_understood": (
            "Per the project brief (NOT yet read against eCFR): keep the "
            "records 1 year where the vehicle is housed or "
            "maintained, and 6 months after it leaves the carrier's "
            "control."),
        "depends": ["assets: retired_at is kept so the 6-month clock can "
                    "be computed; nothing is deleted"],
        "last_checked": None,
        "note": ("eCFR was unreachable from the build environment on Nov 2, "
                 "2026; check before relying on it."),
    },
]
