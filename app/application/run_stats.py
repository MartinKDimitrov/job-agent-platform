"""In-memory metrics collector for one crawl run. Filled by the search/digest use cases and
persisted via app/data/metrics_repo.record_run (which duck-types it — no layering cycle)."""


class RunStats:
    """`.source()` records per-adapter fetch counts/errors; `.add()` accumulates run totals
    (added / deduped / filtered / scored / matched / notified / …)."""

    def __init__(self):
        self.sources: dict[str, dict] = {}
        self.totals: dict[str, int] = {}

    def source(self, name: str, fetched: int = 0, error: str = "") -> None:
        s = self.sources.setdefault(name, {"fetched": 0})
        s["fetched"] += fetched
        if error:
            s["error"] = error

    def add(self, **counts: int) -> None:
        for k, v in counts.items():
            self.totals[k] = self.totals.get(k, 0) + int(v)

    def to_dict(self) -> dict:
        return {"sources": self.sources, "totals": self.totals}
