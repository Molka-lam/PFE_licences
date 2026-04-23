VALID_TRANSITIONS: dict[tuple[str, str], list[str]] = {
    ("requested",   "in_progress"): ["admin", "super_admin"],
    ("in_progress", "active"):      ["admin", "super_admin"],
    ("active",      "suspended"):   ["admin", "super_admin"],
    ("active",      "revoked"):     ["admin", "super_admin"],
    ("suspended",   "active"):      ["admin", "super_admin"],
    ("suspended",   "revoked"):     ["admin", "super_admin"],
    ("active",      "expired"):     ["system"],
    ("suspended",   "expired"):     ["system"],
}


def can_transition(from_status: str, to_status: str, actor_role: str) -> bool:
    """Return True if actor_role is allowed to move from_status → to_status."""
    allowed_roles = VALID_TRANSITIONS.get((from_status, to_status))
    if allowed_roles is None:
        return False
    return actor_role in allowed_roles
