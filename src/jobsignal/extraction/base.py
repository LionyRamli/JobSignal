"""The interface every ATS source (Greenhouse, Lever, Ashby, ...) implements."""

from abc import ABC, abstractmethod
from typing import ClassVar

from jobsignal.models import Posting


class ATSSource(ABC):
    """Fetches the currently open postings for one company from one ATS."""

    name: ClassVar[str]

    @abstractmethod
    def fetch_postings(self, company: str) -> list[Posting]:
        """Return every open posting for ``company`` (the ATS-specific board identifier)."""
