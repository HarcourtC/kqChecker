"""Top-level launcher for kqChecker.

This script is a thin wrapper that either starts the long-running scheduler
or forwards CLI flags to the packaged scheduler module. Example usage:

  python main.py                # start scheduler (same as kq.scheduler.main())
  python main.py --test         # run kq.scheduler in test mode (for next event)
  python main.py --once --dry-run -s weekly.json

The forwarding uses runpy so the module's __main__ path is executed with
the provided args.
"""

from pathlib import Path
import argparse
import runpy
import sys


def main() -> None:
	parser = argparse.ArgumentParser(prog="main.py", description="Launcher for kq.scheduler")
	parser.add_argument("--once", action="store_true", help="Run one immediate pass and exit")
	parser.add_argument("--test", action="store_true", help="Invoke the scheduler in test mode for the next event")
	parser.add_argument("--dry-run", action="store_true", help="When used with --once or --test, skip network calls")
	parser.add_argument("--schedule", "-s", help="Path to schedule JSON file (defaults to weekly.json in project root)")
	args = parser.parse_args()

	# If any of the short-run flags were provided, forward to kq.scheduler's __main__
	if args.once or args.test or args.dry_run or args.schedule:
		module_argv = ["kq.scheduler"]
		if args.once:
			module_argv.append("--once")
		if args.test:
			module_argv.append("--test")
		if args.dry_run:
			module_argv.append("--dry-run")
		if args.schedule:
			module_argv.extend(["--schedule", args.schedule])

		old_argv = sys.argv
		try:
			sys.argv = module_argv
			runpy.run_module("kq.scheduler", run_name="__main__")
		finally:
			sys.argv = old_argv
	else:
		# No CLI flags: start the long-running scheduler in-process
		from kq.scheduler import main as sched_main

		sched_main()


if __name__ == "__main__":
	main()