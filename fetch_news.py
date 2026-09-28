#!/usr/bin/env python3
"""
fetch_news.py
-------------
Povlači najnovije vesti sa 3 kategorije portala (Cyber, Entertainment, AI —
20 portala svaka), uklanja duplirane vesti unutar svake kategorije (kad je
ista vest objavljena na više portala, zadržava se verzija sa portala višeg
ranga sa liste) i generiše docs/index.html — statičan sajt sa 3 taba koji
GitHub Pages servira.

Pokreće ga automatski .github/workflows/update.yml na svaki sat.
Može se pokrenuti i ručno: python fetch_news.py
"""

import json
import re
import html
import difflib
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import feedparser

def gnews(site):
    """Rezervni izvor za sajtove koji blokiraju servere (HTTP 403/503): Google News RSS
    za taj sajt. Daje naslov i link (bez opisa i slike); koristi se tek kad ne uspe nijedna
    druga adresa iz liste "feeds"."""
    return f"https://news.google.com/rss/search?q=site:{site}+when:14d&hl=en-US&gl=US&ceid=US:en"


# ---------------------------------------------------------------------------
# CATEGORIES: svaka kategorija (tab na sajtu) ima svojih 20 portala.
# rang (1 = najkvalitetniji -> koristi se prilikom dupliranja unutar iste
# kategorije), ime, kandidati RSS adresa (proba redom dok jedna ne da
# rezultate), i sajt. Ako neki portal promeni RSS putanju, samo dopuni
# listu "feeds" za njega — skripta preskače izvore koji ne rade i
# nastavlja sa ostalima.
# ---------------------------------------------------------------------------
CATEGORIES = [
    {
        "id": "cyber",
        "label": "Cyber",
        "has_regulations": True,
        "has_severity": True,
        "tagline": "A digest of the latest news from 20 leading cybersecurity portals",
        "sources": [
            {"rank": 1,  "name": "BleepingComputer",     "feeds": ["https://www.bleepingcomputer.com/feed/"], "site": "https://www.bleepingcomputer.com/news/security/", "tag": "Incidents, ransomware, vulnerabilities, and patches"},
            {"rank": 2,  "name": "The Record",           "feeds": ["https://therecord.media/feed"], "site": "https://therecord.media/", "tag": "Cybercrime, geopolitics, and state-sponsored attacks"},
            {"rank": 3,  "name": "SecurityWeek",         "feeds": ["https://www.securityweek.com/feed/"], "site": "https://www.securityweek.com/", "tag": "Enterprise security, ICS/OT, cloud, and threat intelligence"},
            {"rank": 4,  "name": "Dark Reading",         "feeds": ["https://www.darkreading.com/rss.xml", "https://www.darkreading.com/rss_simple.asp"], "site": "https://www.darkreading.com/", "tag": "SOC, SecOps, CISO topics, and expert analysis"},
            {"rank": 5,  "name": "Krebs on Security",    "feeds": ["https://krebsonsecurity.com/feed/"], "site": "https://krebsonsecurity.com/", "tag": "Cybercrime investigations, fraud, and data breaches"},
            {"rank": 6,  "name": "The Hacker News",      "feeds": ["https://feeds.feedburner.com/TheHackersNews", "https://thehackernews.com/feeds/posts/default"], "site": "https://thehackernews.com/", "tag": "Attacks, malware, and vulnerabilities"},
            {"rank": 7,  "name": "Help Net Security",    "feeds": ["https://www.helpnetsecurity.com/feed/"], "site": "https://www.helpnetsecurity.com/", "tag": "Enterprise trends, regulation, and research"},
            {"rank": 8,  "name": "CyberScoop",           "feeds": ["https://cyberscoop.com/feed/"], "site": "https://cyberscoop.com/", "tag": "National security, policy, and international cyber events"},
            {"rank": 9,  "name": "Infosecurity Magazine","feeds": ["https://www.infosecurity-magazine.com/rss/news/"], "site": "https://www.infosecurity-magazine.com/", "tag": "News, analysis, interviews, and research"},
            {"rank": 10, "name": "SC Media",             "feeds": ["https://www.scworld.com/feed", "https://www.scworld.com/feed/topic/threat-management", "https://www.scworld.com/rss.xml", gnews("scworld.com")], "site": "https://www.scworld.com/", "tag": "CISO topics, compliance, cloud, and risk management"},
            {"rank": 11, "name": "Risky Business News",  "feeds": ["https://risky.biz/feeds/risky-business-news/"], "site": "https://news.risky.biz/", "tag": "Daily roundup of cyber events and research"},
            {"rank": 12, "name": "CSO Online",           "feeds": ["https://www.csoonline.com/feed/"], "site": "https://www.csoonline.com/", "tag": "Strategy, leadership, budgets, and regulation"},
            {"rank": 13, "name": "Security Affairs",     "feeds": ["https://securityaffairs.com/feed"], "site": "https://securityaffairs.com/", "tag": "APT groups, malware, vulnerabilities, and incidents"},
            {"rank": 14, "name": "Cybersecurity Dive",   "feeds": ["https://www.cybersecuritydive.com/feeds/news/"], "site": "https://www.cybersecuritydive.com/", "tag": "Business impact of incidents, regulation, and strategy"},
            {"rank": 15, "name": "BankInfoSecurity",     "feeds": ["https://www.bankinfosecurity.com/rssFeeds.php?type=main"], "site": "https://www.bankinfosecurity.com/", "tag": "Financial sector, fraud, identity, and data protection"},
            {"rank": 16, "name": "Cybernews",            "feeds": ["https://cybernews.com/feed/", "https://cybernews.com/security/feed/", gnews("cybernews.com")], "site": "https://cybernews.com/security/", "tag": "Data breach events, privacy, and cybercrime"},
            {"rank": 17, "name": "TechCrunch Security",  "feeds": ["https://techcrunch.com/category/security/feed/"], "site": "https://techcrunch.com/category/security/", "tag": "Tech companies, cloud, and startup incidents"},
            {"rank": 18, "name": "WIRED Security",       "feeds": ["https://www.wired.com/feed/category/security/latest/rss"], "site": "https://www.wired.com/category/security/", "tag": "Privacy, surveillance, and major incidents"},
            {"rank": 19, "name": "Ars Technica Security","feeds": ["https://arstechnica.com/security/feed/"], "site": "https://arstechnica.com/security/", "tag": "Technical analysis of vulnerabilities, attacks, and platforms"},
            {"rank": 20, "name": "CISA",                 "feeds": ["https://www.cisa.gov/cybersecurity-advisories/all.xml", gnews("cisa.gov/news-events")], "site": "https://www.cisa.gov/news-events/cybersecurity-advisories", "tag": "Authoritative alerts and recommended actions"},
        ],
    },
    {
        "id": "entertainment",
        "label": "Entertainment",
        "has_regulations": False,
        "has_severity": False,
        "tagline": "A digest of the latest news from 20 leading music & film portals",
        "sources": [
            {"rank": 1,  "name": "BrooklynVegan",     "feeds": ["https://www.brooklynvegan.com/feed/"], "site": "https://www.brooklynvegan.com/", "tag": "Indie, punk, and underground music news"},
            {"rank": 2,  "name": "Variety",           "feeds": ["https://variety.com/feed/"], "site": "https://variety.com/", "tag": "Film, TV, and entertainment industry business news"},
            {"rank": 3,  "name": "The Hollywood Reporter", "feeds": ["https://www.hollywoodreporter.com/feed/"], "site": "https://www.hollywoodreporter.com/", "tag": "Entertainment industry news, box office, and awards"},
            {"rank": 4,  "name": "PopMatters",        "feeds": ["https://www.popmatters.com/feed"], "site": "https://www.popmatters.com/", "tag": "Music, film, and pop culture criticism"},
            {"rank": 5,  "name": "Pitchfork",         "feeds": ["https://pitchfork.com/feed/feed-news/rss", "https://pitchfork.com/rss/news/"], "site": "https://pitchfork.com/", "tag": "Music reviews, news, and features"},
            {"rank": 6,  "name": "NME",               "feeds": ["https://www.nme.com/feed"], "site": "https://www.nme.com/", "tag": "Music news, reviews, and pop culture"},
            {"rank": 7,  "name": "Consequence",       "feeds": ["https://consequence.net/feed/"], "site": "https://consequence.net/", "tag": "Music, film, and TV news and reviews"},
            {"rank": 8,  "name": "Stereogum",         "feeds": ["https://www.stereogum.com/feed/"], "site": "https://www.stereogum.com/", "tag": "Indie and alternative music news"},
            {"rank": 9,  "name": "AllMusic",          "feeds": ["https://www.allmusic.com/newfeatures.xml", gnews("allmusic.com/blog")], "discover": ["https://www.allmusic.com/rss-feeds"], "site": "https://www.allmusic.com/", "tag": "Music database, reviews, and new releases"},
            {"rank": 10, "name": "Resident Advisor",  "feeds": ["https://ra.co/xml/rss.xml", "https://ra.co/xml/news.xml", gnews("ra.co/news")], "site": "https://ra.co/", "tag": "Electronic music news, reviews, and events"},
            {"rank": 11, "name": "IndieWire",         "feeds": ["https://www.indiewire.com/feed/"], "site": "https://www.indiewire.com/", "tag": "Independent film and TV news and criticism"},
            {"rank": 12, "name": "Deadline",          "feeds": ["https://deadline.com/feed/"], "site": "https://deadline.com/", "tag": "Breaking entertainment industry and Hollywood news"},
            {"rank": 13, "name": "Empire",            "feeds": ["https://www.empireonline.com/feed/", "https://www.empireonline.com/rss/"], "site": "https://www.empireonline.com/", "tag": "Film news, reviews, and features"},
            {"rank": 14, "name": "Collider",          "feeds": ["https://collider.com/feed/"], "site": "https://collider.com/", "tag": "Movie and TV news, reviews, and interviews"},
            {"rank": 15, "name": "The A.V. Club",     "feeds": ["https://www.avclub.com/rss", "https://www.avclub.com/feed/rss"], "site": "https://www.avclub.com/", "tag": "Pop culture news, reviews, and commentary"},
            {"rank": 16, "name": "Screen Rant",       "feeds": ["https://screenrant.com/feed/"], "site": "https://screenrant.com/", "tag": "Movie, TV, and pop culture news"},
            {"rank": 17, "name": "RogerEbert.com",    "feeds": ["https://www.rogerebert.com/feed"], "site": "https://www.rogerebert.com/", "tag": "Film reviews and criticism"},
            {"rank": 18, "name": "/Film (SlashFilm)", "feeds": ["https://www.slashfilm.com/feed/"], "site": "https://www.slashfilm.com/", "tag": "Movie news, reviews, and industry analysis"},
            {"rank": 19, "name": "Little White Lies",  "feeds": ["https://lwlies.com/feed/"], "site": "https://lwlies.com/", "tag": "Film criticism and cinema culture"},
            {"rank": 20, "name": "The Film Stage",    "feeds": ["https://thefilmstage.com/feed/"], "site": "https://thefilmstage.com/", "tag": "Film news, reviews, and festival coverage"},
        ],
    },
    {
        "id": "ai",
        "label": "AI",
        "has_regulations": False,
        "has_severity": False,
        "tagline": "A digest of the latest news from 20 leading AI portals",
        "sources": [
            {"rank": 1,  "name": "BAIR Blog",           "feeds": ["https://bair.berkeley.edu/blog/feed.xml"], "site": "https://bair.berkeley.edu/blog/", "tag": "Berkeley AI research papers and announcements"},
            {"rank": 2,  "name": "TechCrunch AI",       "feeds": ["https://techcrunch.com/category/artificial-intelligence/feed/"], "site": "https://techcrunch.com/category/artificial-intelligence/", "tag": "AI industry news, funding, and product launches"},
            {"rank": 3,  "name": "The Verge AI",        "feeds": ["https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"], "site": "https://www.theverge.com/ai-artificial-intelligence", "tag": "AI product news and industry analysis"},
            {"rank": 4,  "name": "Ars Technica AI",     "feeds": ["https://arstechnica.com/ai/feed/"], "site": "https://arstechnica.com/ai/", "tag": "Technical AI news and analysis"},
            {"rank": 5,  "name": "VentureBeat AI",      "feeds": ["https://venturebeat.com/category/ai/feed/"], "site": "https://venturebeat.com/ai/", "tag": "Enterprise AI news and industry trends"},
            {"rank": 6,  "name": "OpenAI News",         "feeds": ["https://openai.com/news/rss.xml"], "site": "https://openai.com/news/", "tag": "Official OpenAI product and research announcements"},
            {"rank": 7,  "name": "Anthropic News",      "feeds": ["https://raw.githubusercontent.com/taobojlen/anthropic-rss-feed/main/anthropic_news_rss.xml"], "site": "https://www.anthropic.com/news", "tag": "Official Anthropic product and research announcements"},
            {"rank": 8,  "name": "Google DeepMind Blog","feeds": ["https://deepmind.google/blog/rss.xml", gnews("deepmind.google/blog")], "site": "https://deepmind.google/discover/blog/", "tag": "DeepMind research and model announcements"},
            {"rank": 9,  "name": "Hugging Face Blog",   "feeds": ["https://huggingface.co/blog/feed.xml"], "site": "https://huggingface.co/blog", "tag": "Open-source AI models and tooling updates"},
            {"rank": 10, "name": "The Batch",           "feeds": ["https://www.deeplearning.ai/the-batch/feed/", "https://www.deeplearning.ai/feed/", gnews("deeplearning.ai/the-batch"), gnews("deeplearning.ai")], "site": "https://www.deeplearning.ai/the-batch/", "tag": "Weekly AI research and industry roundup"},
            {"rank": 11, "name": "Google AI",           "feeds": ["https://blog.google/technology/ai/rss/"], "site": "https://blog.google/technology/ai/", "tag": "Google's AI research and product announcements"},
            {"rank": 12, "name": "KDnuggets",           "feeds": ["https://www.kdnuggets.com/feed"], "site": "https://www.kdnuggets.com/", "tag": "Data science, machine learning, and AI news"},
            {"rank": 13, "name": "The Rundown AI",      "feeds": ["https://www.therundown.ai/feed"], "site": "https://www.therundown.ai/", "tag": "Daily AI news roundup"},
            {"rank": 14, "name": "TLDR AI",             "feeds": ["https://tldr.tech/api/rss/ai"], "site": "https://tldr.tech/ai", "tag": "Daily AI news digest for practitioners"},
            {"rank": 15, "name": "Stanford HAI News",   "feeds": ["https://hai.stanford.edu/news/feed", "https://hai.stanford.edu/news/rss.xml", "https://hai.stanford.edu/rss.xml", "https://hai.stanford.edu/news/all/rss", gnews("hai.stanford.edu/news")], "site": "https://hai.stanford.edu/news", "tag": "Academic AI research and policy analysis"},
            {"rank": 16, "name": "AI Business",         "feeds": ["https://aibusiness.com/rss.xml", "https://aibusiness.com/rss"], "site": "https://aibusiness.com/", "tag": "Enterprise AI adoption and industry news"},
            {"rank": 17, "name": "Artificial Intelligence News", "feeds": ["https://www.artificialintelligence-news.com/feed/", gnews("artificialintelligence-news.com")], "site": "https://www.artificialintelligence-news.com/", "tag": "AI industry news and analysis"},
            {"rank": 18, "name": "Unite.AI",            "feeds": ["https://www.unite.ai/feed/", gnews("unite.ai")], "site": "https://www.unite.ai/", "tag": "AI news, tools, and industry coverage"},
            {"rank": 19, "name": "MarkTechPost",        "feeds": ["https://www.marktechpost.com/feed/"], "site": "https://www.marktechpost.com/", "tag": "AI research paper summaries and news"},
            {"rank": 20, "name": "IEEE Spectrum AI",    "feeds": ["https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss"], "site": "https://spectrum.ieee.org/artificial-intelligence", "tag": "Technical AI and robotics engineering news"},
        ],
    },
]

MAX_PER_SOURCE = 12           # koliko najnovijih stavki uzimamo po portalu
MAX_TOTAL = 150                # gornja granica ukupnog broja vesti po kategoriji
TOKEN_OVERLAP_THRESHOLD = 0.38 # Jaccard prag na značajnim (stemovanim) rečima -> duplikat
CHAR_SIMILARITY_THRESHOLD = 0.82  # dodatni, stroži character-level prag
SUMMARY_MAX_LEN = 220

TAG_RE = re.compile(r"<[^>]+>")

STOPWORDS = {
    "the","a","an","of","in","on","for","to","and","or","with","after","over",
    "from","new","says","say","said","its","it","is","are","as","by","at",
    "this","that","into","than","but","be","has","have","had","will","can",
    "amid","amidst","two","three","how","why","what","who","more","most",
    "now","out","up","down","off","not","no","yes","via","per","vs",
}


def clean_text(raw: str) -> str:
    """Ukloni HTML tagove i entitete, sažmi razmake."""
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def stem(word: str) -> str:
    """Vrlo jednostavno 'skidanje' množine/nastavaka, dovoljno da 'airport'
    i 'airports', ili 'breach' i 'breaches', budu prepoznati kao ista reč."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def significant_tokens(title: str) -> set:
    """Reči iz naslova bez uobičajenih stop-reči i kratkih tokena — koriste
    se za poređenje po smislu (koje reči se pominju), ne po redosledu slova."""
    words = normalize_title(title).split()
    return {stem(w) for w in words if w not in STOPWORDS and len(w) >= 3}


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "dozen": 12,
}


def extract_plain_numbers(title: str) -> set:
    """Izvuci 'obične' brojeve (npr. broj ranjivosti) iz naslova, ali NE
    CVE identifikatore ni godine — te posebno tretiramo kao jak signal
    da su dve vesti isti/različit događaj (npr. 'CISA dodaje SEDAM' vs
    'CISA dodaje DVA' propusta su različite objave iako je struktura ista)."""
    t = title.lower()
    t_wo_cve = re.sub(r"cve-\d{4}-\d+", " ", t)
    nums = {int(n) for n in re.findall(r"\b\d{1,3}\b", t_wo_cve) if not (1990 <= int(n) <= 2035)}
    for word, val in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", t_wo_cve):
            nums.add(val)
    return nums


def titles_are_duplicates(title_a: str, title_b: str) -> bool:
    """Dve vesti se smatraju duplikatom ako dele dovoljno veliki udeo
    značajnih reči (Jaccard sličnost) ILI ako su skoro identične karakter-po-karakter,
    OSIM ako obe pominju različite 'obične' brojeve (npr. broj ranjivosti) —
    to je jak signal da je reč o dva različita događaja sa sličnom strukturom
    naslova (tipično kod CISA/patch-utorak objava)."""
    nums_a, nums_b = extract_plain_numbers(title_a), extract_plain_numbers(title_b)
    if nums_a and nums_b and not (nums_a & nums_b):
        return False

    tokens_a, tokens_b = significant_tokens(title_a), significant_tokens(title_b)
    if tokens_a and tokens_b:
        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        if jaccard >= TOKEN_OVERLAP_THRESHOLD:
            return True
    char_ratio = difflib.SequenceMatcher(None, normalize_title(title_a), normalize_title(title_b)).ratio()
    return char_ratio >= CHAR_SIMILARITY_THRESHOLD


def entry_datetime(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def entry_category(entry) -> str:
    tags = entry.get("tags")
    if tags:
        term = tags[0].get("term")
        if term:
            return clean_text(term)
    return "News"


# ---------------------------------------------------------------------------
# Slike uz vesti: prvo iz samog RSS-a (media:thumbnail, media:content,
# enclosure, <img> u sadrzaju); ako ih nema, og:image sa stranice clanka.
# ---------------------------------------------------------------------------
OG_TIMEOUT_SEC = 8
OG_MAX_BYTES = 300_000
OG_TOTAL_BUDGET_SEC = 150
OG_WORKERS = 12
OG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SIGNAL20-NewsDigest"
)

IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
ATTR_RE = re.compile(r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
IMG_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|avif|gif)(?:\?|$)", re.I)
BAD_IMG_HINTS = ("pixel", "tracking", "1x1", "spacer", "blank.gif", "feedburner",
                 "doubleclick", "/emoji/", "gravatar.com", "avatar")
OG_KEYS = ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src")


def normalize_image_url(raw, base=None):
    """Vrati upotrebljiv https URL slike ili None (data: URI, pikseli, avatari...)."""
    if not raw:
        return None
    u = html.unescape(str(raw)).strip()
    if not u or u.startswith("data:"):
        return None
    if u.startswith("//"):
        u = "https:" + u
    elif base and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", u):
        u = urljoin(base, u)
    if not u.lower().startswith(("http://", "https://")):
        return None
    if u.lower().startswith("http://"):
        u = "https://" + u[7:]
    low = u.lower()
    if any(h in low for h in BAD_IMG_HINTS):
        return None
    return u


def first_img_from_html(markup):
    if not markup:
        return None
    for tag in IMG_TAG_RE.findall(markup):
        attrs = {}
        for m in ATTR_RE.finditer(tag):
            attrs[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
        if attrs.get("width", "").strip() in ("0", "1") or attrs.get("height", "").strip() in ("0", "1"):
            continue
        for key in ("src", "data-src", "data-lazy-src", "data-original"):
            u = normalize_image_url(attrs.get(key))
            if u:
                return u
    return None


def entry_image(entry):
    for t in entry.get("media_thumbnail") or []:
        u = normalize_image_url(t.get("url"))
        if u:
            return u
    for m in entry.get("media_content") or []:
        typ = (m.get("type") or "").lower()
        medium = (m.get("medium") or "").lower()
        url = m.get("url") or ""
        if typ.startswith("image") or medium == "image" or (not typ and not medium and IMG_EXT_RE.search(url)):
            u = normalize_image_url(url)
            if u:
                return u
    for e in entry.get("enclosures") or []:
        if (e.get("type") or "").lower().startswith("image"):
            u = normalize_image_url(e.get("href") or e.get("url"))
            if u:
                return u
    for l in entry.get("links") or []:
        if l.get("rel") == "enclosure" and (l.get("type") or "").lower().startswith("image"):
            u = normalize_image_url(l.get("href"))
            if u:
                return u
    for c in entry.get("content") or []:
        u = first_img_from_html(c.get("value"))
        if u:
            return u
    return first_img_from_html(entry.get("summary") or entry.get("description"))


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = {}

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            d = {k.lower(): v for k, v in attrs if k}
            key = (d.get("property") or d.get("name") or "").lower()
            if key in OG_KEYS and d.get("content"):
                self.found.setdefault(key, d["content"])


def fetch_og_image(page_url):
    """URL slike sa stranice clanka; "" ako je stranica ucitana ali nema slike;
    None ako je doslo do privremene greske (pokusace se ponovo pri sledecem pokretanju)."""
    try:
        req = Request(page_url, headers={"User-Agent": OG_USER_AGENT,
                                         "Accept": "text/html,application/xhtml+xml"})
        with urlopen(req, timeout=OG_TIMEOUT_SEC) as resp:
            final_url = resp.geturl()
            raw = resp.read(OG_MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
        parser = MetaParser()
        try:
            parser.feed(raw.decode(charset, errors="replace"))
        except Exception:
            pass
        for key in OG_KEYS:
            if key in parser.found:
                u = normalize_image_url(parser.found[key], base=final_url)
                if u:
                    return u
        return ""
    except HTTPError as exc:
        return "" if exc.code in (401, 403, 404, 410, 451) else None
    except Exception:
        return None


IMAGE_STATE = {"cache": {}, "deadline": 0.0}


def load_image_cache():
    """Slike pronadjene u prethodnom pokretanju (docs/news.json) ne traze se ponovo."""
    IMAGE_STATE["deadline"] = time.time() + OG_TOTAL_BUDGET_SEC
    path = Path(__file__).parent / "docs" / "news.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        for tab in old.values():
            for n in tab.get("news", []):
                if n.get("url") and isinstance(n.get("image"), str):
                    IMAGE_STATE["cache"][n["url"]] = n["image"]
    except Exception:
        pass
    print(f"Ke\u0161 slika iz prethodnog pokretanja: {len(IMAGE_STATE['cache'])} stavki")


def fill_missing_images(items):
    cache = IMAGE_STATE["cache"]
    todo = []
    for n in items:
        if n.get("image"):
            continue
        if n["url"].startswith("https://news.google.com/"):
            n["image"] = ""  # Google News link vodi na preusmerenje, ne na stranicu clanka
            continue
        if n["url"] in cache:
            n["image"] = cache[n["url"]]
        else:
            todo.append(n)
    if not todo:
        return
    print(f"  Tra\u017eim og:image za {len(todo)} vesti bez slike...")
    ex = ThreadPoolExecutor(max_workers=OG_WORKERS)
    futures = {ex.submit(fetch_og_image, n["url"]): n for n in todo}
    found = 0
    try:
        remaining = max(1.0, IMAGE_STATE["deadline"] - time.time())
        for fut in as_completed(futures, timeout=remaining):
            n = futures[fut]
            res = fut.result()
            if res is None:
                continue
            n["image"] = res
            cache[n["url"]] = res
            if res:
                found += 1
    except Exception:
        print("  [!] Isteklo ukupno vreme za pretragu slika, preostale se presko\u010de.")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    print(f"  Na\u0111eno slika: {found}")


# ---------------------------------------------------------------------------
# Povlacenje feed-ova: browser-like zaglavlja + timeout, automatsko trazenje
# feed-a na sajtu (<link rel="alternate">) i dijagnostika u docs/feed_status.json
# ---------------------------------------------------------------------------
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
FEED_TIMEOUT_SEC = 25
FEED_ACCEPT = ("application/rss+xml, application/atom+xml, application/xml;q=0.9, "
               "text/xml;q=0.8, text/html;q=0.5, */*;q=0.3")
GENERIC_FEED_PATHS = ["/feed/", "/feed", "/rss.xml", "/rss/", "/rss", "/atom.xml", "/index.xml", "/feed.xml"]
FEED_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
ANCHOR_RE = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+)[\"']", re.I)
FEED_WORKERS = 8

STATUS_LOG = []
PRIOR_STATUS = {}


OWN_UA = "SIGNAL20-NewsDigest/1.0 (+https://milejelic-del.github.io/cybernews/)"
# Redosled: UA biblioteke za feed-ove (neki sajtovi ga dozvoljavaju, a browser UA blokiraju),
# zatim identifikovani UA ovog sajta, pa generican browser UA.
UA_CANDIDATES = [("feedparser", feedparser.USER_AGENT), ("identified", OWN_UA), ("browser", BROWSER_UA)]
BLOCK_CODES = (401, 403, 406, 429)


def http_get(url, ua, timeout=FEED_TIMEOUT_SEC):
    req = Request(url, headers={"User-Agent": ua, "Accept": FEED_ACCEPT,
                                "Accept-Language": "en-US,en;q=0.9"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(5_000_000), resp.geturl()


def describe_error(exc):
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    return f"{type(exc).__name__}: {str(exc)[:80]}"


def get_with_rotation(url):
    """Isti URL sa razlicitim User-Agent-ima dok neki ne prodje (samo kod blokada)."""
    last = None
    for label, ua in UA_CANDIDATES:
        try:
            raw, final = http_get(url, ua)
            return raw, final, label
        except HTTPError as exc:
            last = exc
            if exc.code not in BLOCK_CODES:
                raise
    raise last


def try_feed(url):
    """Vrati (parsed ili None, opis rezultata, koji UA je prosao)."""
    notes = []
    for label, ua in UA_CANDIDATES:
        try:
            raw, _final = http_get(url, ua)
        except HTTPError as exc:
            notes.append(f"HTTP {exc.code} ({label})")
            if exc.code in BLOCK_CODES:
                continue
            break
        except Exception as exc:
            notes.append(f"{describe_error(exc)} ({label})")
            break
        parsed = feedparser.parse(raw)
        if parsed.entries:
            extra = (" [pre toga: " + "; ".join(notes) + "]") if notes else ""
            return parsed, f"OK {len(parsed.entries)} stavki (UA: {label})" + extra, label
        is_html = raw[:300].lstrip().lower().startswith((b"<!doctype html", b"<html"))
        notes.append(("odgovor je HTML, nije feed" if is_html else "feed je prazan ili neprepoznat") + f" ({label})")
        if is_html:
            continue
        break
    return None, "; ".join(notes), None


def discover_feed_urls(page_url, scan_anchors=False):
    """Nadji adrese feed-ova na stranici: <link rel=alternate type=rss/atom>,
    a za 'discover' stranice i linkove koji lice na feed."""
    raw, final, _ua = get_with_rotation(page_url)
    text = raw.decode("utf-8", errors="replace")
    found = []
    for tag in FEED_LINK_RE.findall(text):
        attrs = {}
        for m in ATTR_RE.finditer(tag):
            attrs[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
        rel = (attrs.get("rel") or "").lower()
        typ = (attrs.get("type") or "").lower()
        if "alternate" in rel and ("rss" in typ or "atom" in typ) and attrs.get("href"):
            found.append(urljoin(final, html.unescape(attrs["href"])))
    if scan_anchors:
        for m in ANCHOR_RE.finditer(text):
            href = html.unescape(m.group(1))
            low = href.lower()
            if low.endswith((".xml", ".rss")) or "/rss" in low or "/feed" in low:
                found.append(urljoin(final, href))
    out = []
    for u in found:
        if "comments" in u.lower() or u in out:
            continue
        out.append(u)
    return out[:8]


def load_prior_status():
    path = Path(__file__).parent / "docs" / "feed_status.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        for s in old.get("sources", []):
            if s.get("ok") and s.get("used_url"):
                PRIOR_STATUS[s["name"]] = s
    except Exception:
        pass


def entries_to_items(source, parsed):
    items = []
    entries = list(parsed.entries)
    if entries and entries[0].get("link", "").startswith("https://news.google.com/"):
        entries.sort(key=lambda e: e.get("published_parsed") or (0,), reverse=True)
    for entry in entries[:MAX_PER_SOURCE]:
        title = clean_text(entry.get("title", "")).strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue
        if link.startswith("https://news.google.com/"):
            # Google News: naslov ima sufiks " - Naziv sajta", a opis samo ponavlja naslov
            src_title = ((entry.get("source") or {}).get("title") or "").strip()
            for sep in (" - ", " \u2013 ", " \u2014 "):
                if src_title and title.endswith(sep + src_title):
                    title = title[: -len(sep + src_title)].strip()
                    break
            summary = ""
        else:
            summary = clean_text(entry.get("summary", entry.get("description", "")))
        if len(summary) > SUMMARY_MAX_LEN:
            summary = summary[:SUMMARY_MAX_LEN].rsplit(" ", 1)[0] + "\u2026"
        dt = entry_datetime(entry)
        items.append({
            "source": source["name"],
            "rank": source["rank"],
            "title": title,
            "summary": summary,
            "url": link,
            "category": entry_category(entry),
            "date": dt.strftime("%Y-%m-%d"),
            "timestamp": dt.isoformat(),
            "coverage": 1,
            "image": entry_image(entry),
        })
    return items


def fetch_source(source: dict):
    """Vrati (items, status). Redom: prethodno uspesna adresa, zadate adrese,
    adrese pronadjene na sajtu, i (samo za sajtove sa korena) uobicajene putanje."""
    attempts, tried = [], set()
    state = {"parsed": None, "used": None, "via": None, "ua": None}

    def attempt(url, via):
        if url in tried:
            return False
        tried.add(url)
        parsed, result, ua = try_feed(url)
        attempts.append({"url": url, "result": result})
        if parsed:
            state.update(parsed=parsed, used=url, via=via, ua=ua)
            return True
        return False

    declared = list(source["feeds"])
    prior = PRIOR_STATUS.get(source["name"], {}).get("used_url")
    order = ([(prior, "previous")] if prior and prior not in declared else []) + [(u, "declared") for u in declared]
    for url, via in order:
        if attempt(url, via):
            break

    if not state["parsed"]:
        pages = [(p, True) for p in source.get("discover", [])] + [(source["site"], False)]
        for page, scan in pages:
            if state["parsed"]:
                break
            try:
                found = discover_feed_urls(page, scan_anchors=scan)
            except Exception as exc:
                attempts.append({"url": page, "result": "trazenje feed-a: " + describe_error(exc)})
                continue
            if not found:
                attempts.append({"url": page, "result": "trazenje feed-a: nista pronadjeno"})
            for url in found:
                if attempt(url, "discovered"):
                    break

    blocked = any(("HTTP 403" in a["result"] or "HTTP 429" in a["result"]) for a in attempts)
    if not state["parsed"] and not blocked and urlparse(source["site"]).path in ("", "/"):
        base_url = "{u.scheme}://{u.netloc}".format(u=urlparse(source["site"]))
        for path in GENERIC_FEED_PATHS:
            if attempt(base_url + path, "generic"):
                break

    items = entries_to_items(source, state["parsed"]) if state["parsed"] else []
    status = {
        "name": source["name"],
        "ok": bool(items),
        "items": len(items),
        "used_url": state["used"],
        "via": state["via"],
        "ua": state["ua"],
        "attempts": attempts,
    }
    return items, status


def dedupe(items: list) -> list:
    """Kad su dve vesti iz različitih izvora (unutar iste kategorije)
    dovoljno slične po naslovu, zadrži samo onu sa portala nižeg (boljeg)
    ranga sa liste. Poredi se samo unutar prozora od nekoliko dana, jer
    ista vest o istom događaju izlazi na različitim portalima u kratkom
    vremenskom razmaku. Svaki zadržani item dobija "coverage" — broj
    portala koji su pokrili istu priču — koristi se za nedeljni rekap."""
    kept = []
    for item in sorted(items, key=lambda x: x["rank"]):
        item.setdefault("coverage", 1)
        item_dt = datetime.fromisoformat(item["timestamp"])
        is_dup = False
        for existing in kept:
            existing_dt = datetime.fromisoformat(existing["timestamp"])
            if abs((item_dt - existing_dt).total_seconds()) > 4 * 24 * 3600:
                continue
            if titles_are_duplicates(item["title"], existing["title"]):
                existing["coverage"] = existing.get("coverage", 1) + 1
                if not existing.get("image") and item.get("image"):
                    existing["image"] = item["image"]
                is_dup = True
                break
        if not is_dup:
            kept.append(item)
    return kept


def fetch_category(category: dict) -> dict:
    """Povuci, dedupliciraj i pripremi podatke za jednu kategoriju (tab)."""
    results = {}
    with ThreadPoolExecutor(max_workers=FEED_WORKERS) as ex:
        futs = {ex.submit(fetch_source, s): s for s in category["sources"]}
        for fut in as_completed(futs):
            results[futs[fut]["name"]] = fut.result()

    all_items = []
    for source in category["sources"]:
        items, status = results[source["name"]]
        status["tab"] = category["id"]
        STATUS_LOG.append(status)
        if status["ok"]:
            extra = "" if status["via"] == "declared" else f" [{status['via']}: {status['used_url']}]"
            print(f"- {source['name']}: {len(items)} stavki{extra}")
        else:
            print(f"- {source['name']}: BEZ VESTI")
            for a in status["attempts"]:
                print(f"    [x] {a['url']} -> {a['result']}")
        all_items.extend(items)

    print(f"  Ukupno pre deduplikacije: {len(all_items)}")
    deduped = dedupe(all_items)
    print(f"  Nakon deduplikacije: {len(deduped)}")

    deduped.sort(key=lambda x: x["timestamp"], reverse=True)
    deduped = deduped[:MAX_TOTAL]
    fill_missing_images(deduped)

    return {
        "id": category["id"],
        "label": category["label"],
        "hasRegulations": category["has_regulations"],
        "hasSeverity": category["has_severity"],
        "tagline": category["tagline"],
        "news": deduped,
        "sources": [
            {"rank": s["rank"], "name": s["name"], "url": s["site"], "tag": s["tag"]}
            for s in category["sources"]
        ],
    }


def build_html(data_by_tab: dict) -> str:
    template_path = Path(__file__).parent / "template.html"
    template = template_path.read_text(encoding="utf-8")

    data_json = json.dumps(data_by_tab, ensure_ascii=False, indent=2)
    generated_at_iso = datetime.now(timezone.utc).isoformat()

    out = template.replace("__DATA_JSON__", data_json)
    out = out.replace("__GENERATED_AT_ISO__", generated_at_iso)
    return out


def main():
    load_image_cache()
    load_prior_status()
    data_by_tab = {}
    for category in CATEGORIES:
        print(f"\n=== {category['label']} ({len(category['sources'])} portala) ===")
        data_by_tab[category["id"]] = fetch_category(category)

    out_dir = Path(__file__).parent / "docs"
    out_dir.mkdir(exist_ok=True)

    (out_dir / "index.html").write_text(build_html(data_by_tab), encoding="utf-8")
    (out_dir / "news.json").write_text(
        json.dumps(data_by_tab, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "feed_status.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "sources": STATUS_LOG},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    totals = {cid: len(d["news"]) for cid, d in data_by_tab.items()}
    print(f"\nGenerisano: {out_dir / 'index.html'} — {totals}")


if __name__ == "__main__":
    main()
