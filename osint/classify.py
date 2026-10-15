"""출처 성격 분류: 정부·공공 / 기업 발표 / 언론.

채널마다 기본 성격이 있고, 구글 뉴스·RSS가 알려준 출처 사이트가 정부·기업 사이트면 그쪽을 따른다.
(예: 현지 지방 매체 검색에 주지사실 보도자료가 걸리면 '정부·공공'으로 본다)
"""

KINDS = {"gov": "정부·공공", "corp": "기업 발표", "media": "언론"}
KIND_ORDER = ["gov", "corp", "media"]

CHANNEL_KIND = {
    "sec": "gov", "courts": "gov", "nhtsa": "gov", "fed_register": "gov", "us_federal": "gov",
    "gov_press": "gov", "eu_comp": "gov", "china_gov": "gov", "kr_gov": "gov",
    "pr_wire": "corp",
    "local_media": "media", "trade_media": "media", "china_media": "media", "global_media": "media",
    "feeds": "media", "news_en": "media", "news_zh": "media",
}

# 이 접미사로 끝나는 사이트는 정부·공공기관
GOV_SUFFIXES = (
    "gov", "mil", "gov.cn", "go.kr", "korea.kr", "europa.eu", "gov.uk", "gc.ca", "go.jp", "gob.mx",
    "gov.in", "gouv.fr", "gov.au", "gov.br", "gob.es", "bund.de", "gv.at", "admin.ch", "gov.pl",
    "gov.hu", "gov.cz", "gov.sk", "gov.vn", "go.id", "go.th", "gov.my", "gov.sg", "gov.tr",
    "courtlistener.com", "uscourts.gov",
)
# 정부 산하 투자유치기관 등 .gov가 아닌 공공 사이트
GOV_DOMAINS = (
    "georgia.org", "madeinalabama.com", "sccommerce.com", "selectusa.gov", "investinbsr.com",
    "michiganbusiness.org", "jobsohio.com", "edpnc.com", "tnecd.com", "texaswideopenforbusiness.com",
)
CORP_DOMAINS = (
    "prnewswire.com", "businesswire.com", "globenewswire.com", "accessnewswire.com", "accesswire.com",
    "newsfilecorp.com", "einpresswire.com", "prweb.com",
    "hyundainews.com", "kiamedia.com", "hyundai.com", "kia.com", "genesis.com", "hyundaimotorgroup.com",
    "hmgjournal.com", "lgensol.com", "samsungsdi.com", "sk.com", "skon.com", "posco.com", "hankooktire.com",
    "news.gm.com", "media.ford.com", "stellantis.com", "media.stellantis.com", "toyota.com",
    "pressroom.toyota.com", "tesla.com", "rivian.com", "panasonic.com",
)


def _match(domain, names):
    return any(domain == n or domain.endswith("." + n) for n in names)


def domain_kind(domain):
    """사이트 주소로 판단한 성격(모르면 None)."""
    d = (domain or "").lower().strip(".")
    if d.startswith("www."):
        d = d[4:]
    if not d:
        return None
    if _match(d, GOV_DOMAINS) or any(d == s or d.endswith("." + s) for s in GOV_SUFFIXES):
        return "gov"
    if _match(d, CORP_DOMAINS):
        return "corp"
    return None


def kind_of(signal):
    return domain_kind(signal.meta.get("domain")) or CHANNEL_KIND.get(signal.channel, "media")


def kind_label(kind):
    return KINDS.get(kind, kind)
