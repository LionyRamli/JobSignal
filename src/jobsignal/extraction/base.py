"""The interface every ATS source (Greenhouse, Lever, Ashby, ...) implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from jobsignal.models import Posting


@dataclass(frozen=True)
class FetchResult:
    """Postings from one fetch, plus how many entries were skipped as malformed.

    ``complete`` is False when anything was skipped: callers must then not infer that
    absent postings were closed (an upstream glitch is not a hiring freeze).
    """

    postings: list[Posting]
    skipped: int = 0

    @property
    def complete(self) -> bool:
        return self.skipped == 0


class ATSSource(ABC):
    """Fetches the currently open postings for one company from one ATS."""

    name: ClassVar[str]

    @abstractmethod
    def fetch(self, company: str) -> FetchResult:
        """Fetch every open posting for ``company`` (the ATS-specific board identifier)."""

    def fetch_postings(self, company: str) -> list[Posting]:
        return self.fetch(company).postings
