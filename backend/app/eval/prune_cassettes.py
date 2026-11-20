"""Delete recorded model answers that no current run uses (e.g. recorded with an older prompt version).

    NHTSA_LLM_MODE=replay uv run python -m app.eval.run --set demo        (replays touch the files they use)
    NHTSA_LLM_MODE=replay uv run python -m app.eval.run --set a,b,c
    uv run python -m app.eval.prune_cassettes --minutes 30                 (delete files not used in the last 30 min)
"""
import argparse
import time

from app.config import get_settings


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, required=True, help="keep files used within this many minutes")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    cutoff = time.time() - a.minutes * 60
    files = sorted(get_settings().cassette_dir.glob("*.json"))
    stale = [f for f in files if f.stat().st_mtime < cutoff]
    for f in stale if not a.dry_run else []:
        f.unlink()
    print(f"{len(files)} recordings, {len(stale)} unused {'(would delete)' if a.dry_run else 'deleted'}")


if __name__ == "__main__":
    main()
