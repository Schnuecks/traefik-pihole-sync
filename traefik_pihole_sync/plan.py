"""Pure planning logic: which records to add or delete in one Pi-hole.

Nothing in here talks to the network, which keeps the safety rules easy to test.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .records import AAAA, CNAME, A, Record


@dataclass
class Plan:
    add: list[Record] = field(default_factory=list)
    # Managed records that are present in Pi-hole and must be removed.
    delete: list[Record] = field(default_factory=list)
    # Managed records that are already gone from Pi-hole; only drop them from the state.
    forget: list[Record] = field(default_factory=list)
    # Stale managed records waiting for DELETE_THRESHOLD, with their miss count.
    deferred: dict[Record, int] = field(default_factory=dict)
    # Names we want to write but which carry records we did not create.
    conflicts: set[str] = field(default_factory=set)

    @property
    def changes(self) -> int:
        return len(self.add) + len(self.delete) + len(self.forget)


def desired_records(
    hostnames: Iterable[str],
    record_type: str,
    target_ip: str | None = None,
    target_ipv6: str | None = None,
    cname_target: str | None = None,
) -> set[Record]:
    """Translate hostnames into the records this tool should maintain."""
    records: set[Record] = set()
    hostnames = {h.strip().lower() for h in hostnames if h and h.strip()}

    def add_addresses(name: str) -> None:
        if target_ip:
            records.add(Record(A, name, target_ip))
        if target_ipv6:
            records.add(Record(AAAA, name, target_ipv6))

    if record_type == CNAME:
        if not cname_target:
            raise ValueError("CNAME mode needs a CNAME target")
        target = cname_target.strip().lower()
        for name in hostnames:
            if name != target:
                records.add(Record(CNAME, name, target))
        add_addresses(target)
    else:
        for name in hostnames:
            add_addresses(name)
    return records


def build_plan(
    desired: set[Record],
    existing: set[Record],
    managed: set[Record],
    missing: dict[Record, int],
    delete_threshold: int,
) -> Plan:
    """Compare the wanted state with Pi-hole and the records we own.

    Safety rules:
    * Only records in ``managed`` (created by this tool) are ever deleted.
    * A name that carries records we did not create is not touched.
    * A record that vanished from Traefik is deleted only after it was missing
      ``delete_threshold`` times in a row. If its name is still wanted (e.g. the
      target IP changed) the old record is replaced right away.
    """
    plan = Plan()
    desired_names = {r.name for r in desired}
    foreign_names = {r.name for r in existing if r not in managed and r not in desired}

    for record in sorted(desired - existing):
        if record.name in foreign_names:
            plan.conflicts.add(record.name)
        else:
            plan.add.append(record)

    for record in sorted(managed - desired):
        if record.name not in desired_names:
            count = missing.get(record, 0) + 1
            if count < delete_threshold:
                plan.deferred[record] = count
                continue
        if record in existing:
            plan.delete.append(record)
        else:
            plan.forget.append(record)

    return plan
