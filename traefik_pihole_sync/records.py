"""DNS record model shared by the planner, the Pi-hole client and the state file."""

from __future__ import annotations

from dataclasses import dataclass

A = "A"
AAAA = "AAAA"
CNAME = "CNAME"
RECORD_TYPES = (A, AAAA, CNAME)


@dataclass(frozen=True, order=True)
class Record:
    """A single local DNS record.

    For A/AAAA records ``value`` is the IP address, for CNAME records it is the target name.
    """

    type: str
    name: str
    value: str

    def __post_init__(self) -> None:
        if self.type not in RECORD_TYPES:
            raise ValueError(f"unknown record type: {self.type!r}")
        object.__setattr__(self, "name", self.name.strip().lower())
        value = self.value.strip()
        object.__setattr__(self, "value", value.lower() if self.type == CNAME else value)

    def __str__(self) -> str:
        return f"{self.name} {self.type} {self.value}"

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict) -> Record:
        return cls(type=data["type"], name=data["name"], value=data["value"])
