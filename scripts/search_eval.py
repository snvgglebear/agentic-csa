#!/usr/bin/env python3
"""
Measure search quality on questions phrased the way students ask them.

Each case lists URL fragments of pages that answer it. A case passes at k
when one of those pages is in the top k results. Cases with no answer list
are topics the docs don't cover: they pass when the search flags its
results as weak matches.

Usage:
    uv run python scripts/search_eval.py          # summary
    uv run python scripts/search_eval.py -v       # every case
"""

import argparse
import asyncio
import logging
import sys

CASES: list[tuple[str, list[str]]] = [
    ("how do I view logs from a match", ["telemetry/datalog", "datalog-download", "view-your-datalog",
                                         "view-my-datalog", "overview/log-files", "log-viewer"]),
    ("home my elevator with a limit switch", ["home-a-mechanism"]),
    ("zero the arm encoder at a hard stop", ["home-a-mechanism", "encoders-software"]),
    ("robot browns out when driving", ["roborio-brownouts", "improving-performance-with-current-limits"]),
    ("set current limits on a talon fx", ["improving-performance-with-current-limits"]),
    ("set a current limit on a spark max", ["make-it-spin", "basic-config", "configuring-a-spark", "home/faq"]),
    ("bind a command to a button", ["binding-commands-to-triggers"]),
    ("swerve odometry", ["swerve-drive-odometry"]),
    ("slew rate limiter joystick", ["slew-rate-limiter"]),
    ("debounce a sensor", ["debouncer"]),
    ("trapezoid motion profile", ["trapezoidal-profiles", "motion-profiles"]),
    ("tune PID on a flywheel", ["tuning-flywheel"]),
    ("feedforward for an arm with gravity", ["tuning-vertical-arm", "feed-forward-control", "feedforward"]),
    ("sysid characterize the drivetrain", ["system-identification", "sysid-integration"]),
    ("apriltag pose estimation with photonvision", ["robot-pose-estimator", "multitag"]),
    ("limelight megatag2", ["megatag2"]),
    ("pathplanner named commands", ["pplib-named-commands"]),
    ("advantagekit log replay", ["traditional-replay", "replay-watch", "log-replay"]),
    ("simulate a mechanism", ["simulate", "simulation", "mech2d-widget"]),
    ("spark max closed loop position control", ["closed-loop", "position-control-mode"]),
    ("cancoder magnet offset", ["cancoder"]),
    ("log values with epilogue", ["robot-telemetry-with-annotations"]),
    ("run two commands at the same time", ["command-compositions"]),
    ("why does my robot stop responding when a while loop runs", ["command-scheduler", "commands", "loop"]),
    ("build an autonomous routine with pathplanner", ["pplib-build-an-auto"]),
    ("view my match logs in advantagescope", ["overview/log-files", "view-your-datalog", "view-my-datalog",
                                              "telemetry/datalog", "datalog-download"]),
    # Topics the docs don't cover: results should be flagged as weak
    ("sensorless homing using stall current detection", []),
    ("how to bake a chocolate cake", []),
]


async def run(verbose: bool, router=None) -> tuple[int, int, int, int]:
    """Score every case. Starts the server unless a router is given."""
    if router is None:
        from wpilib_mcp import server

        logging.disable(logging.CRITICAL)
        await server.initialize_server()
        router = server._router

    top1 = top3 = weak_ok = answerable = 0
    for query, answers in CASES:
        results = await router.search(query=query, vendors=["all"], language="Java", max_results=3)
        urls = [r.url for r in results]
        weak = bool(results) and results[0].weak_match
        if answers:
            answerable += 1
            rank = next((i for i, u in enumerate(urls) if any(a in u for a in answers)), None)
            top1 += rank == 0
            top3 += rank is not None
            ok = rank is not None and not weak
            weak_ok += not weak
            mark = "ok " if rank == 0 else ("top3" if rank is not None else "MISS")
        else:
            ok = weak or not results
            weak_ok += ok
            mark = "ok " if ok else "NOT FLAGGED"
        if verbose or not ok:
            print(f"[{mark}] {query!r}{'  (flagged weak)' if weak and answers else ''}")
            for r in results:
                print(f"         {r.vendor[:12]:12} {r.url.split('//')[-1][:90]}")
    return top1, top3, weak_ok, answerable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="show every case")
    args = parser.parse_args()
    top1, top3, weak_ok, answerable = asyncio.run(run(args.verbose))
    total = len(CASES)
    print(f"\nRight page first:  {top1}/{answerable}")
    print(f"Right page in top 3: {top3}/{answerable}")
    print(f"Weak flag correct:   {weak_ok}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
