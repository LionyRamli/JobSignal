"""Thin entry point; logic lives in jobsignal.detect so it is importable and tested."""

import sys

from jobsignal.detect import main

if __name__ == "__main__":
    sys.exit(main())
