"""DEMO ONLY: back up jobsignal.db, then seed synthetic hiring history (see jobsignal.seed_demo)."""

import sys

from jobsignal.seed_demo import main

if __name__ == "__main__":
    sys.exit(main())
