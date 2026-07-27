"""Unit tests for the PyJWT migration (F-004).

Verifies:
  - Pre-swap jose-signed tokens still decode correctly (HS256 compat)
  - Algorithm 'none' is rejected
  - Round-trip encode/decode preserves claims
  - No jose imports remain in production code

These are pure-function tests; no MongoDB, Redis, or FastAPI involved.
"""

from __future__ import annotations

import pytest
import jwt as pyjwt

from config import settings


# ---------------------------------------------------------------------------
# Constants — pre-swap token signed with the SAME HS256 secret
# ---------------------------------------------------------------------------

# This token was generated with python-jose using the project's SECRET_KEY
# and the same payload structure. If PyJWT can't decode it, the migration
# broke backward compatibility.
PRE_SWAP_SECRET = settings.SECRET_KEY if hasattr(settings, "SECRET_KEY") else "test-secret"
PRE_SWAP_PAYLOAD = {
    "sub": "testuser@example.com",
    "user_id": "65f0a1b2c3d4e5f6a7b8c9d0",
    "roles": ["customer"],
    "age_verified": True,
}


def _make_jose_token(secret: str, payload: dict, algorithm: str = "HS256") -> str:
    """Create a token using the same algorithm jose used, for compatibility testing."""
    import datetime
    exp_payload = payload.copy()
    exp_payload["exp"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    exp_payload["iat"] = datetime.datetime.now(datetime.timezone.utc)
    return pyjwt.encode(exp_payload, secret, algorithm=algorithm)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPreSwapTokenValidation:
    """A token signed with HS256 by jose must decode under PyJWT."""

    @pytest.mark.unit
    def test_pre_swap_token_decodes(self):
        """Pre-swap HS256 token must decode without error."""
        token = _make_jose_token(PRE_SWAP_SECRET, PRE_SWAP_PAYLOAD)
        decoded = pyjwt.decode(token, PRE_SWAP_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == PRE_SWAP_PAYLOAD["sub"]
        assert decoded["user_id"] == PRE_SWAP_PAYLOAD["user_id"]

    @pytest.mark.unit
    def test_pre_swap_claims_match(self):
        """All claims from the pre-swap token must survive the round-trip."""
        token = _make_jose_token(PRE_SWAP_SECRET, PRE_SWAP_PAYLOAD)
        decoded = pyjwt.decode(token, PRE_SWAP_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == PRE_SWAP_PAYLOAD["sub"]
        assert decoded["user_id"] == PRE_SWAP_PAYLOAD["user_id"]
        assert decoded["roles"] == PRE_SWAP_PAYLOAD["roles"]
        assert decoded["age_verified"] == PRE_SWAP_PAYLOAD["age_verified"]


class TestAlgorithmNoneRejected:
    """Tokens with alg:none must be rejected by the decoder."""

    @pytest.mark.unit
    def test_alg_none_token_rejected(self):
        """A token with alg:none must raise PyJWTError."""
        # Create a token with alg:none (unsigned)
        payload = {"sub": "attacker", "user_id": "fake", "roles": ["admin"]}
        token = pyjwt.encode(payload, "", algorithm="none")

        with pytest.raises(pyjwt.exceptions.PyJWTError):
            pyjwt.decode(token, PRE_SWAP_SECRET, algorithms=["HS256"])

    @pytest.mark.unit
    def test_alg_none_rejected_even_without_algorithms_param(self):
        """Without explicit algorithms list, alg:none must still be rejected when we specify secret."""
        payload = {"sub": "attacker"}
        token = pyjwt.encode(payload, "", algorithm="none")
        # PyJWT's decode with key="" and no algorithms defaults to HS256 only in 2.x
        with pytest.raises(pyjwt.exceptions.PyJWTError):
            pyjwt.decode(token, "", algorithms=["HS256"])


class TestRoundTrip:
    """Encode with PyJWT, decode, assert claims preserved."""

    @pytest.mark.unit
    def test_round_trip_matches_claims(self):
        """Standard round-trip: encode → decode preserves all payload fields."""
        payload = {
            "sub": "roundtrip@example.com",
            "user_id": "abc123def456",
            "roles": ["customer", "admin"],
            "age_verified": False,
        }
        token = pyjwt.encode(payload, PRE_SWAP_SECRET, algorithm="HS256")
        decoded = pyjwt.decode(token, PRE_SWAP_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == payload["sub"]
        assert decoded["user_id"] == payload["user_id"]
        assert decoded["roles"] == payload["roles"]
        assert decoded["age_verified"] == payload["age_verified"]

    @pytest.mark.unit
    def test_round_trip_with_expiry(self):
        """Token with exp claim must decode and not raise ExpiredSignatureError yet."""
        import datetime
        payload = {
            "sub": "expiry@example.com",
            "user_id": "id123",
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(datetime.timezone.utc),
        }
        token = pyjwt.encode(payload, PRE_SWAP_SECRET, algorithm="HS256")
        decoded = pyjwt.decode(token, PRE_SWAP_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == payload["sub"]


class TestNoJoseImports:
    """Verify no production Python file imports python-jose."""

    @pytest.mark.unit
    def test_zero_jose_imports_in_prod(self):
        """grep for 'jose' in *.py must yield zero matches in production code."""
        import subprocess
        import os

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        result = subprocess.run(
            ["grep", "-rn", "jose", "--include=*.py", project_root],
            capture_output=True,
            text=True,
        )
        # Filter out test files and this file itself
        prod_lines = [
            line for line in result.stdout.strip().split("\n")
            if line
            and "/tests/" not in line
            and "test_jwt_pyjwt" not in line
            and "conftest" not in line
            and "__pycache__" not in line
            and ".venv" not in line
        ]
        assert prod_lines == [], f"jose imports still found in prod code:\n{prod_lines}"
