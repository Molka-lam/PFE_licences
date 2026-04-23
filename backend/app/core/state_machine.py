VALID_TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("requested",   "in_progress"): frozenset({"admin", "super_admin"}),
    ("in_progress", "active"):      frozenset({"admin", "super_admin"}),
    ("active",      "suspended"):   frozenset({"admin", "super_admin"}),
    ("active",      "revoked"):     frozenset({"admin", "super_admin"}),
    ("suspended",   "active"):      frozenset({"admin", "super_admin"}),
    ("suspended",   "revoked"):     frozenset({"admin", "super_admin"}),
    ("active",      "expired"):     frozenset({"system"}),
    ("suspended",   "expired"):     frozenset({"system"}),
}


def can_transition(from_status: str, to_status: str, actor_role: str) -> bool:
    """Return True if actor_role is allowed to move from_status → to_status."""
    allowed_roles = VALID_TRANSITIONS.get((from_status, to_status))
    if allowed_roles is None:
        return False
    return actor_role in allowed_roles
