"""Thin entry point; logic lives in jobsignal.scrape so it is importable and tested."""

import sys

from jobsignal.scrape import main

if __name__ == "__main__":
    sys.exit(main())
