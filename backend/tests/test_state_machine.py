import pytest
from app.core.state_machine import can_transition, VALID_TRANSITIONS

def test_all_valid_transitions():
    for (from_s, to_s), roles in VALID_TRANSITIONS.items():
        for role in roles:
            assert can_transition(from_s, to_s, role), f"{from_s}→{to_s} should allow {role}"

def test_invalid_transition():
    assert not can_transition("requested", "active", "admin")  # must go through in_progress

def test_wrong_role_blocked():
    assert not can_transition("requested", "in_progress", "client")

def test_system_only_for_expiry():
    assert can_transition("active", "expired", "system")
    assert not can_transition("active", "expired", "admin")

def test_unknown_from_status():
    assert not can_transition("nonexistent", "active", "admin")

def test_revoked_is_terminal():
    for (from_s, _) in VALID_TRANSITIONS:
        assert from_s != "revoked", f"revoked must be terminal, found outgoing transition from it"
    assert not can_transition("revoked", "active", "admin")
    assert not can_transition("revoked", "suspended", "super_admin")

def test_expired_is_terminal():
    assert not can_transition("expired", "active", "admin")
