
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class NewsArticle:
    id: int
    source: Optional[str]
    headline: str
    url: str
    published_at: Optional[datetime]
    description: Optional[str]
    fetched_at: Optional[datetime]

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "headline": self.headline,
            "url": self.url,
            "published_at": (
                self.published_at.isoformat()
                if self.published_at else None
            ),
            "description": self.description,
            "fetched_at": (
                self.fetched_at.isoformat()
                if self.fetched_at else None
            ),
        }
