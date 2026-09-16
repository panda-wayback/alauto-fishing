"""无头跑局 CLI：PYTHONPATH=src python -m algo"""

from __future__ import annotations

import argparse

from algo.runner import run_batch, run_episode
from algo.threshold_hold import ThresholdHoldPolicy
from sim.game import State


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="无头批量测拉鱼策略")
    p.add_argument("--tier", type=int, default=4, choices=range(1, 9))
    p.add_argument("--episodes", type=int, default=50)
    p.add_argument("--low", type=float, default=50.0, help="低于此 pos 按住")
    p.add_argument("--high", type=float, default=90.0, help="高于此 pos 松开")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)

    def make() -> ThresholdHoldPolicy:
        return ThresholdHoldPolicy(low=args.low, high=args.high, seed=args.seed)

    batch = run_batch(make(), episodes=args.episodes, tier=args.tier)
    print(
        f"tier=T{args.tier} episodes={batch.episodes} "
        f"win_rate={batch.win_rate:.1%} "
        f"avg_time={batch.avg_time:.2f}s avg_progress={batch.avg_progress:.3f}"
    )
    one = run_episode(make(), tier=args.tier)
    print(f"sample episode: {one.state.name} time={one.time:.2f}s progress={one.progress:.3f}")
    return 0 if batch.wins > 0 or one.state == State.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
