"""기사 수집: 네이버 뉴스 검색 API, 외부 파일(모니터링 프로그램 결과), 취재 자료 폴더."""

import csv
import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"

PRESS_BY_DOMAIN = {
    "yna.co.kr": "연합뉴스", "hankyung.com": "한국경제", "mk.co.kr": "매일경제",
    "sedaily.com": "서울경제", "edaily.co.kr": "이데일리", "mt.co.kr": "머니투데이",
    "biz.chosun.com": "조선비즈", "chosun.com": "조선일보", "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보", "hani.co.kr": "한겨레", "khan.co.kr": "경향신문",
    "newsis.com": "뉴시스", "news1.kr": "뉴스1", "asiae.co.kr": "아시아경제",
    "fnnews.com": "파이낸셜뉴스", "heraldcorp.com": "헤럴드경제", "etnews.com": "전자신문",
    "kbs.co.kr": "KBS", "imbc.com": "MBC", "sbs.co.kr": "SBS", "ytn.co.kr": "YTN",
    "hankookilbo.com": "한국일보", "seoul.co.kr": "서울신문", "kmib.co.kr": "국민일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "dt.co.kr": "디지털타임스",
    "ajunews.com": "아주경제", "newspim.com": "뉴스핌", "inews24.com": "아이뉴스24",
    "zdnet.co.kr": "지디넷코리아", "bloter.net": "블로터", "motorgraph.com": "모터그래프",
    "bizwatch.co.kr": "비즈니스워치", "thebell.co.kr": "더벨",
}


@dataclass
class Article:
    title: str
    link: str
    description: str = ""
    press: str = ""
    published: datetime | None = None
    keyword: str = ""
    source: str = "naver"
    id: str = ""
    tags: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


def clean_text(text):
    """네이버 API 결과의 <b> 태그와 HTML 엔티티를 걷어낸다."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def press_from_url(url, extra_map=None):
    host = urllib.parse.urlparse(url or "").netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    table = {**PRESS_BY_DOMAIN, **(extra_map or {})}
    # 하위 도메인까지 고려해 가장 긴 도메인부터 대조
    for domain in sorted(table, key=len, reverse=True):
        if host == domain or host.endswith("." + domain):
            return table[domain]
    return host


def parse_date(value):
    """RFC822(네이버), ISO8601, 'YYYY-MM-DD HH:MM' 등을 받아 tz-aware datetime으로."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=_kst())
    value = str(value).strip()
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=_kst())
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=_kst())
    except ValueError:
        return None


def _kst():
    return timezone(timedelta(hours=9))


# ---------------------------------------------------------------- 네이버 API

def fetch_naver(keyword, pages=1, client_id=None, client_secret=None, press_map=None):
    client_id = client_id or os.environ.get("NAVER_CLIENT_ID")
    client_secret = client_secret or os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없습니다. "
            "네이버 개발자센터에서 검색 API 키를 발급받아 설정하거나, --input 으로 기사 파일을 넣으세요."
        )
    articles = []
    for page in range(pages):
        query = urllib.parse.urlencode(
            {"query": keyword, "display": 100, "start": 1 + page * 100, "sort": "date"}
        )
        req = urllib.request.Request(
            f"{NAVER_URL}?{query}",
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        items = data.get("items", [])
        for item in items:
            original = item.get("originallink") or item.get("link")
            articles.append(Article(
                title=clean_text(item.get("title")),
                link=original,
                description=clean_text(item.get("description")),
                press=press_from_url(original, press_map),
                published=parse_date(item.get("pubDate")),
                keyword=keyword,
                source="naver",
            ))
        if len(items) < 100:
            break
    return articles


# ---------------------------------------------------------------- 외부 파일

_FIELD_ALIASES = {
    "title": ["title", "제목", "headline"],
    "link": ["originallink", "link", "url", "링크", "주소"],
    "description": ["description", "summary", "요약", "본문", "content", "body"],
    "press": ["press", "source", "언론사", "매체", "media"],
    "published": ["pubDate", "published", "date", "datetime", "날짜", "일시", "시간"],
    "keyword": ["keyword", "query", "키워드", "검색어"],
}


def _pick(row, name):
    for key in _FIELD_ALIASES[name]:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return ""


def load_articles(path, press_map=None):
    """모니터링 프로그램이 저장한 JSON/CSV를 읽는다. 필드명은 영문·한글 모두 허용."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            rows = data.get("items") or data.get("articles") or []
        else:
            rows = data
    articles = []
    for row in rows:
        title = clean_text(_pick(row, "title"))
        if not title:
            continue
        link = _pick(row, "link")
        articles.append(Article(
            title=title,
            link=link,
            description=clean_text(_pick(row, "description")),
            press=_pick(row, "press") or press_from_url(link, press_map),
            published=parse_date(_pick(row, "published")),
            keyword=_pick(row, "keyword"),
            source=p.name,
        ))
    return articles


def save_articles(articles, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump([a.to_dict() for a in articles], f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 취재 자료

def load_materials(directory):
    """기자가 직접 넣은 자료(보도자료·메모 등 .txt/.md)를 읽는다."""
    if not directory:
        return []
    d = Path(directory)
    if not d.is_dir():
        raise FileNotFoundError(f"자료 폴더가 없습니다: {d}")
    materials = []
    for f in sorted(d.iterdir()):
        if f.suffix.lower() in (".txt", ".md") and f.is_file():
            materials.append({"name": f.name, "text": f.read_text(encoding="utf-8").strip()})
    return materials
