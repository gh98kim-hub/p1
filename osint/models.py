"""수집 신호 형식."""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Signal:
    channel: str            # 채널 키(sec, courts, nhtsa, gov_press …)
    title: str
    url: str
    published: datetime | None = None
    source: str = ""        # 매체·기관명
    text: str = ""          # 요약·발췌(원문 일부)
    lang: str = "en"
    query: str = ""         # 어떤 검색으로 들어왔는지
    meta: dict = field(default_factory=dict)
    entities: list = field(default_factory=list)   # 추적 대상 이름(한국어 대표명)
    locations: list = field(default_factory=list)  # 지역 이름
    first_seen: datetime | None = None
    is_new: bool = True

    @property
    def uid(self):
        key = self.meta.get("uid") or self.url or f"{self.channel}:{self.title}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    def to_dict(self):
        d = asdict(self)
        for k in ("published", "first_seen"):
            d[k] = d[k].isoformat() if d[k] else None
        return d
