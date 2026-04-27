from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from autofin.schemas import PermissionSet


@dataclass(frozen=True)
class PermissionPolicy:
    allowed_network: List[str] = field(default_factory=list)
    allowed_filesystem: List[str] = field(default_factory=lambda: ["write_temp"])
    allowed_secrets: List[str] = field(default_factory=list)

    def validate(self, requested: PermissionSet) -> None:
        denied_network = sorted(set(requested.network) - set(self.allowed_network))
        denied_filesystem = sorted(set(requested.filesystem) - set(self.allowed_filesystem))
        denied_secrets = sorted(set(requested.secrets) - set(self.allowed_secrets))

        if denied_network or denied_filesystem or denied_secrets:
            raise PermissionError(
                "Skill requested permissions outside policy: "
                f"network={denied_network}, "
                f"filesystem={denied_filesystem}, "
                f"secrets={denied_secrets}"
            )
