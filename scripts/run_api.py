"""Thin entry point; logic lives in jobsignal.api.serve so it is importable and tested."""

import sys

from jobsignal.api.serve import main

if __name__ == "__main__":
    sys.exit(main())
