from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


@dataclass
class OrderIntent:
    symbol: str
    side: str
    quantity: float
    reference_price: float
    reason: str
    sector: str = "Technology"


@dataclass
class LedgerEntry:
    entry_id: str
    run_id: str
    entry_type: str
    actor: str
    payload: dict
    created_at: str
    payload_hash: str
    previous_hash: str
    entry_hash: str


class CausalLedger:
    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def append(self, run_id: str, entry_type: str, actor: str, payload: dict) -> LedgerEntry:
        previous = self.entries[-1].entry_hash if self.entries else "GENESIS"
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(raw.encode()).hexdigest()
        material = f"{run_id}|{entry_type}|{actor}|{payload_hash}|{previous}"
        entry_hash = hashlib.sha256(material.encode()).hexdigest()
        entry = LedgerEntry(uid(), run_id, entry_type, actor, payload, now(), payload_hash, previous, entry_hash)
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous = "GENESIS"
        for entry in self.entries:
            raw = json.dumps(entry.payload, sort_keys=True, separators=(",", ":"))
            payload_hash = hashlib.sha256(raw.encode()).hexdigest()
            material = f"{entry.run_id}|{entry.entry_type}|{entry.actor}|{payload_hash}|{previous}"
            if entry.payload_hash != payload_hash or entry.previous_hash != previous or entry.entry_hash != hashlib.sha256(material.encode()).hexdigest():
                return False
            previous = entry.entry_hash
        return True

    def json(self) -> list[dict]:
        return [asdict(x) for x in self.entries]


@dataclass
class Run:
    run_id: str
    event: dict
    status: str
    created_at: str
    agents: list[dict] = field(default_factory=list)
    proposals: list[dict] = field(default_factory=list)
    parliament: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    order: dict | None = None
    autopsy: dict | None = None
    replay_of: str | None = None

    def json(self) -> dict:
        return asdict(self)
