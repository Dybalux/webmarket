"""Unit tests for password policy enforcement (F-009).

Verifies:
  - Strong password accepted (MyD0g$W0rld!23)
  - Short password rejected (< 12 chars)
  - Missing character class rejected (no uppercase, no digit, etc.)
  - Common password rejected (blocklisted)
  - Pre-policy 8-char passwords are NOT retroactively checked at login

These are pure-Pydantic tests; no MongoDB, Redis, or FastAPI involved.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import UserRegister, PasswordResetConfirm, COMMON_PASSWORDS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_register(password: str) -> dict:
    """Return valid UserRegister data with a controllable password."""
    return {
        "username": "testuser",
        "email": "test@example.com",
        "password": password,
        "birth_date": "2000-01-01T00:00:00",
    }


def _make_reset(password: str) -> dict:
    """Return valid PasswordResetConfirm data with a controllable password."""
    return {
        "token": "any-token-value",
        "new_password": password,
    }


# ---------------------------------------------------------------------------
# Strong password — must pass
# ---------------------------------------------------------------------------

class TestStrongPasswordAccepted:
    @pytest.mark.unit
    def test_strong_password_accepted(self):
        """MyD0g$W0rld!23 meets all policy requirements."""
        data = _make_register("MyD0g$W0rld!23")
        user = UserRegister(**data)
        assert user.password == "MyD0g$W0rld!23"

    @pytest.mark.unit
    def test_strong_password_with_all_special_chars(self):
        """Password with all special characters accepted."""
        data = _make_register("Abcdef1!@#$%^&*")
        user = UserRegister(**data)
        assert user.password == "Abcdef1!@#$%^&*"


# ---------------------------------------------------------------------------
# Short password — rejected
# ---------------------------------------------------------------------------

class TestShortPasswordRejected:
    @pytest.mark.unit
    def test_short_password_rejected(self):
        """Ab1! is only 4 chars — must fail min_length=12."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("Ab1!"))
        errors = exc_info.value.errors()
        assert any(
            "at least 12" in err["msg"].lower() or "12" in err["msg"]
            for err in errors
        ), f"Expected 12-char minimum error, got: {errors}"

    @pytest.mark.unit
    def test_eleven_char_password_rejected(self):
        """Exactly 11 characters — must be rejected."""
        with pytest.raises(ValidationError):
            UserRegister(**_make_register("Abcdefgh1!x"))

    @pytest.mark.unit
    def test_exactly_12_char_strong_password_accepted(self):
        """Exactly 12 characters with all classes — must pass."""
        data = _make_register("Abcdefgh1!x2")
        user = UserRegister(**data)
        assert len(user.password) == 12


# ---------------------------------------------------------------------------
# Missing character class — rejected
# ---------------------------------------------------------------------------

class TestMissingCharacterClass:
    @pytest.mark.unit
    def test_no_uppercase_rejected(self):
        """All lowercase + digit + special — no uppercase."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("abcdefgh1!xyz"))
        errors = exc_info.value.errors()
        assert any("uppercase" in err["msg"].lower() for err in errors)

    @pytest.mark.unit
    def test_no_lowercase_rejected(self):
        """All uppercase + digit + special — no lowercase."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("ABCDEFGHI1!XYZ"))
        errors = exc_info.value.errors()
        assert any("lowercase" in err["msg"].lower() for err in errors)

    @pytest.mark.unit
    def test_no_digit_rejected(self):
        """Upper + lower + special — no digit."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("Abcdefgh!xyz"))
        errors = exc_info.value.errors()
        assert any("digit" in err["msg"].lower() for err in errors)

    @pytest.mark.unit
    def test_no_special_rejected(self):
        """Upper + lower + digit — no special character."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("Abcdefgh1xyz2"))
        errors = exc_info.value.errors()
        assert any("special" in err["msg"].lower() for err in errors)


# ---------------------------------------------------------------------------
# Common password — rejected
# ---------------------------------------------------------------------------

class TestCommonPasswordRejected:
    @pytest.mark.unit
    def test_common_password_rejected(self):
        """password1234 is in the blocklist (12 chars) — must be rejected as common."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("password1234"))
        errors = exc_info.value.errors()
        assert any("common" in err["msg"].lower() for err in errors)

    @pytest.mark.unit
    def test_common_password_case_insensitive(self):
        """PASSWORD1234 (uppercase) — blocklist check is case-insensitive."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("PASSWORD1234"))
        errors = exc_info.value.errors()
        assert any("common" in err["msg"].lower() for err in errors)

    @pytest.mark.unit
    def test_short_common_password_fails_on_length_first(self):
        """password123 (11 chars) fails on length before common check."""
        with pytest.raises(ValidationError) as exc_info:
            UserRegister(**_make_register("password123"))
        errors = exc_info.value.errors()
        assert any("12" in err["msg"] for err in errors)

    @pytest.mark.unit
    def test_another_common_password_rejected(self):
        """1234567890 is in the blocklist."""
        with pytest.raises(ValidationError):
            UserRegister(**_make_register("1234567890"))

    @pytest.mark.unit
    def test_blocklist_is_not_empty(self):
        """Sanity: the blocklist actually has entries."""
        assert len(COMMON_PASSWORDS) > 20


# ---------------------------------------------------------------------------
# PasswordResetConfirm — same policy applies
# ---------------------------------------------------------------------------

class TestResetPasswordPolicy:
    @pytest.mark.unit
    def test_strong_reset_password_accepted(self):
        """Strong password accepted for reset."""
        data = _make_reset("MyD0g$W0rld!23")
        reset = PasswordResetConfirm(**data)
        assert reset.new_password == "MyD0g$W0rld!23"

    @pytest.mark.unit
    def test_weak_reset_password_rejected(self):
        """Weak password rejected for reset — policy is shared."""
        with pytest.raises(ValidationError):
            PasswordResetConfirm(**_make_reset("123"))

    @pytest.mark.unit
    def test_common_reset_password_rejected(self):
        """Common password (>= 12 chars) rejected for reset."""
        with pytest.raises(ValidationError):
            PasswordResetConfirm(**_make_reset("password1234"))

    @pytest.mark.unit
    def test_short_reset_password_rejected(self):
        """Short password rejected for reset."""
        with pytest.raises(ValidationError):
            PasswordResetConfirm(**_make_reset("Ab1!"))


# ---------------------------------------------------------------------------
# Pre-policy passwords NOT re-checked at login
# ---------------------------------------------------------------------------

class TestPrePolicyPasswordsNotReChecked:
    @pytest.mark.unit
    def test_login_schema_has_no_password_policy(self):
        """UserLogin.password has no field_validator — login never checks policy.

        This test verifies that the login schema does not import or apply
        the password strength validator. Pre-policy users can still log in
        with their original 8-char password.
        """
        from models import UserLogin

        # A short password that would fail policy — must NOT raise here
        # because UserLogin has no password validator
        login = UserLogin(email_or_username="olduser@example.com", password="shortpw")
        assert login.password == "shortpw"

    @pytest.mark.unit
    def test_common_password_allowed_for_login(self):
        """A common password is allowed at login time (policy applies only to register/reset)."""
        from models import UserLogin

        login = UserLogin(email_or_username="olduser@example.com", password="password")
        assert login.password == "password"
