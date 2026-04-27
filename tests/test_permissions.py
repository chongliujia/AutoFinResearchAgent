import pytest

from autofin.runtime import PermissionPolicy
from autofin.schemas import PermissionSet


def test_permission_policy_accepts_allowed_permissions():
    policy = PermissionPolicy(allowed_network=["sec.gov"])

    policy.validate(PermissionSet(network=["sec.gov"], filesystem=["write_temp"]))


def test_permission_policy_rejects_denied_network():
    policy = PermissionPolicy(allowed_network=["sec.gov"])

    with pytest.raises(PermissionError):
        policy.validate(PermissionSet(network=["example.com"], filesystem=["write_temp"]))
