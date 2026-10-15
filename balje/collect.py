"""기사 수집: 네이버 뉴스 검색 API, 외신(구글 뉴스 RSS), 기사 본문, 외부 파일, 취재 자료 폴더."""

import csv
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

NAVER_URL = "https://openapi.naver.com/v1/search/news.json"
GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

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
    naver_link: str = ""   # 네이버 뉴스 페이지(있으면 본문 수집에 우선 사용)
    lang: str = "ko"       # "en"이면 외신
    body: str = ""         # 수집한 본문(발제 후보만)
    title_ko: str = ""     # 외신 제목 번역

    def to_dict(self):
        d = asdict(self)
        d["published"] = self.published.isoformat() if self.published else None
        return d


def clean_text(text):
    """네이버 API 결과의 <b> 태그와 HTML 엔티티를 걷어낸다."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_link(url):
    """스킴이 빠진 링크(www.… 또는 //…)를 열 수 있는 주소로 고친다."""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        return "https://" + url
    return url


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
            "네이버 API 키가 없습니다. 네이버 개발자센터에서 검색 API 키를 발급받아 "
            "설정(프로그램의 [설정] 또는 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수)하거나, "
            "기사 파일을 불러오세요."
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
            original = normalize_link(item.get("originallink") or item.get("link"))
            naver = item.get("link") or ""
            articles.append(Article(
                title=clean_text(item.get("title")),
                link=original,
                naver_link=naver if "news.naver.com" in naver else "",
                description=clean_text(item.get("description")),
                press=press_from_url(original, press_map),
                published=parse_date(item.get("pubDate")),
                keyword=keyword,
                source="naver",
            ))
        if len(items) < 100:
            break
    return articles


# ---------------------------------------------------------------- 외신(구글 뉴스 RSS)

def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset()
    return raw, charset


def parse_google_news(xml_bytes, query=""):
    root = ET.fromstring(xml_bytes)
    articles = []
    for item in root.iter("item"):
        title = clean_text(item.findtext("title"))
        source_el = item.find("source")
        press = clean_text(source_el.text) if source_el is not None and source_el.text else ""
        # 구글 뉴스 제목 끝의 ' - 매체명' 제거
        if press and title.endswith(" - " + press):
            title = title[: -len(press) - 3].strip()
        desc = clean_text(item.findtext("description"))
        if desc.startswith(title):
            desc = ""
        articles.append(Article(
            title=title,
            link=normalize_link(item.findtext("link")),
            description=desc,
            press=press or "외신",
            published=parse_date(item.findtext("pubDate")),
            keyword=query,
            source="google_news",
            lang="en",
        ))
    return articles


def fetch_google_news(query, hl="en-US", gl="US", ceid="US:en"):
    url = GOOGLE_NEWS_URL + "?" + urllib.parse.urlencode({"q": query, "hl": hl, "gl": gl, "ceid": ceid})
    raw, _ = _http_get(url)
    return parse_google_news(raw, query)


# ---------------------------------------------------------------- 기사 본문

class _TextGrabber(HTMLParser):
    """본문 후보 영역의 텍스트를 모은다. 스크립트·스타일·사진설명 등은 건너뛴다.

    실제 기사 HTML은 태그가 제대로 닫히지 않는 경우가 많아, 깊이 대신 '같은 이름 태그'의
    열고 닫힘만 세어 영역의 끝을 찾는다.
    """

    SKIP = {"script", "style", "noscript", "iframe", "figure", "figcaption", "button", "aside", "nav",
            "footer", "em"}
    BODY_IDS = ("dic_area", "newsct_article", "articleBodyContents", "articeBody", "articleBody",
                "article-view-content-div", "article_body", "news_body_area", "CmAdContent")
    BODY_CLASSES = ("article_body", "article-body", "news_body", "story-news", "view_cont", "article_txt")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.target_tag, self.target_n, self.target_done = None, 0, False
        self.skip_tag, self.skip_n = None, 0
        self.target, self.paragraphs, self.article_text = [], [], []
        self._p = None
        self.in_article = 0

    def _in_target(self):
        return self.target_tag is not None and not self.target_done

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "br":
            if self._in_target():
                self.target.append("\n")
            return
        if self.skip_tag is None and tag in self.SKIP and not (tag == "em" and "img_desc" not in (a.get("class") or "")):
            self.skip_tag, self.skip_n = tag, 0
        if self.skip_tag == tag:
            self.skip_n += 1
        if self.target_tag is None:
            ident = a.get("id") or ""
            cls = (a.get("class") or "").split()
            if ident in self.BODY_IDS or any(c in cls for c in self.BODY_CLASSES) \
                    or a.get("itemprop") == "articleBody":
                self.target_tag, self.target_n = tag, 0
        if self._in_target():
            if tag == self.target_tag:
                self.target_n += 1
            if tag in ("p", "div"):
                self.target.append("\n")
        if tag == "article":
            self.in_article += 1
        if tag == "p":
            self._p = []

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self._in_target():
            self.target.append("\n")

    def handle_endtag(self, tag):
        if tag == "p" and self._p is not None:
            text = " ".join("".join(self._p).split())
            if text:
                self.paragraphs.append(text)
            self._p = None
        if tag == "article" and self.in_article:
            self.in_article -= 1
        if self.skip_tag == tag:
            self.skip_n -= 1
            if self.skip_n <= 0:
                self.skip_tag = None
        if self._in_target() and tag == self.target_tag:
            self.target_n -= 1
            if self.target_n <= 0:
                self.target_done = True  # 첫 본문 영역만 사용
        if self._in_target() and tag in ("p", "div", "strong", "b", "h2", "h3", "h4", "li", "tr"):
            self.target.append("\n")

    def handle_data(self, data):
        if self.skip_tag is not None:
            return
        if self._in_target():
            self.target.append(data)
        if self._p is not None:
            self._p.append(data)
        if self.in_article:
            self.article_text.append(data)


def _tidy(text):
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if not line:
            blank = bool(out)
            continue
        if blank:
            out.append("")
        out.append(line)
        blank = False
    return "\n".join(out).strip()


def extract_body(html_text, max_chars=6000):
    """기사 HTML에서 본문만 뽑는다. 네이버 뉴스(dic_area)·주요 언론사 본문 영역 → <p> 묶음 순."""
    g = _TextGrabber()
    try:
        g.feed(html_text)
        g.close()
    except Exception:  # 깨진 HTML도 가능한 만큼만
        pass
    text = _tidy("".join(g.target))
    if len(text) < 80:
        paras = [p for p in g.paragraphs if len(p) >= 30]
        text = "\n\n".join(paras)
    if len(text) < 80:
        text = _tidy("".join(g.article_text))
    if len(text) < 80:
        return ""
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def _decode(raw, charset):
    if not charset:
        m = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', raw[:3000])
        charset = m.group(1).decode() if m else "utf-8"
    charset = charset.lower()
    if charset in ("euc-kr", "ks_c_5601-1987", "ksc5601"):
        charset = "cp949"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch_body(article, max_chars=6000):
    """기사 본문을 가져온다. 네이버 뉴스 링크가 있으면 그것을 먼저 쓴다. 실패하면 빈 문자열."""
    for url in (article.naver_link, article.link):
        if not url or "news.google.com" in url:
            continue
        try:
            raw, charset = _http_get(url)
        except (OSError, ValueError):
            continue
        body = extract_body(_decode(raw, charset), max_chars)
        if body:
            return body
    return ""


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
        link = normalize_link(_pick(row, "link"))
        naver = normalize_link(row.get("link", "")) if "news.naver.com" in str(row.get("link", "")) else ""
        articles.append(Article(
            title=title,
            link=link,
            description=clean_text(_pick(row, "description")),
            press=_pick(row, "press") or press_from_url(link, press_map),
            published=parse_date(_pick(row, "published")),
            keyword=_pick(row, "keyword"),
            source=p.name,
            naver_link=naver,
            lang=row.get("lang") or ("en" if re.fullmatch(r"[\x00-\x7f]+", title) else "ko"),
            body=row.get("body", ""),
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
