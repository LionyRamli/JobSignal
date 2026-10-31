"""Thin entry point; logic lives in jobsignal.harmonize so it is importable and tested."""

import sys

from jobsignal.harmonize import main

if __name__ == "__main__":
    sys.exit(main())
