"""Compare the bounded in-memory cache against the original Git revision.

Run from the repository root: python benchmarks/benchmark_message_store.py
Disk flushing is disabled only for the timed insertions, for both implementations.
"""

import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from platforms.youtube.youtube_message_store import YouTubeMessageStore  # noqa: E402

BASELINE_REVISION = "cbe66c8"
WINDOW_SIZE = 5000
INSERTIONS = 1000
REPEATS = 3


def measure(store_class) -> float:
    samples = []
    for _ in range(REPEATS):
        with tempfile.TemporaryDirectory() as directory:
            store = store_class(Path(directory) / "messages.json", max_messages=WINDOW_SIZE)
            store.save({"messages": [{"message_id": f"old-{i}"} for i in range(WINDOW_SIZE)]})
            store._flush_every_n_changes = 10**9
            store._flush_every_seconds = float("inf")
            started = time.perf_counter()
            for i in range(INSERTIONS):
                store.mark_seen(f"new-{i}", "viewer", "test message")
            samples.append(time.perf_counter() - started)
    return statistics.median(samples)


def main():
    baseline_source = subprocess.run(
        ["git", "show", f"{BASELINE_REVISION}:platforms/youtube/youtube_message_store.py"],
        cwd=ROOT, check=True, capture_output=True, encoding="utf-8-sig",
    ).stdout
    namespace = {"__name__": "baseline_message_store"}
    exec(compile(baseline_source, "baseline_message_store.py", "exec"), namespace)
    baseline = measure(namespace["YouTubeMessageStore"])
    current = measure(YouTubeMessageStore)
    print(json.dumps({
        "baseline_revision": BASELINE_REVISION,
        "window_messages": WINDOW_SIZE,
        "new_messages": INSERTIONS,
        "repeats": REPEATS,
        "baseline_median_seconds": round(baseline, 6),
        "current_median_seconds": round(current, 6),
        "speedup_in_memory": round(baseline / current, 1),
    }, indent=2))


if __name__ == "__main__":
    main()
