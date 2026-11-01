"""Thin entry point; logic lives in jobsignal.dashboard.serve so it is importable and tested."""

import sys

from jobsignal.dashboard.serve import main

if __name__ == "__main__":
    sys.exit(main())
