#!/usr/bin/env python3
"""
fetch_news.py
-------------
Povlači najnovije vesti sa 20 cyber security portala putem njihovih RSS
feed-ova, uklanja duplirane vesti (kad je ista vest objavljena na više
portala, zadržava se verzija sa portala višeg ranga sa liste) i generiše
docs/index.html — statičan sajt koji GitHub Pages servira.

Pokreće ga automatski .github/workflows/update.yml na svaki sat.
Može se pokrenuti i ručno: python fetch_news.py
"""

import json
import re
import html
import difflib
from datetime import datetime, timezone
from pathlib import Path

import feedparser

# ---------------------------------------------------------------------------
# 20 portala: rang (1 = najkvalitetniji -> koristi se prilikom dupliranja),
# ime, kandidati RSS adresa (proba redom dok jedna ne da rezultate), i sajt.
# Ako neki portal promeni RSS putanju, samo dopuni listu "feeds" za njega —
# skripta preskače izvore koji ne rade i nastavlja sa ostalima.
# ---------------------------------------------------------------------------
SOURCES = [
    {"rank": 1,  "name": "BleepingComputer",     "feeds": ["https://www.bleepingcomputer.com/feed/"], "site": "https://www.bleepingcomputer.com/news/security/", "tag": "Incidenti, ransomware, ranjivosti i zakrpe"},
    {"rank": 2,  "name": "The Record",           "feeds": ["https://therecord.media/feed"], "site": "https://therecord.media/", "tag": "Cybercrime, geopolitika i državno sponzorisani napadi"},
    {"rank": 3,  "name": "SecurityWeek",         "feeds": ["https://www.securityweek.com/feed/"], "site": "https://www.securityweek.com/", "tag": "Enterprise bezbednost, ICS/OT, cloud i threat intelligence"},
    {"rank": 4,  "name": "Dark Reading",         "feeds": ["https://www.darkreading.com/rss.xml", "https://www.darkreading.com/rss_simple.asp"], "site": "https://www.darkreading.com/", "tag": "SOC, SecOps, CISO teme i stručne analize"},
    {"rank": 5,  "name": "Krebs on Security",    "feeds": ["https://krebsonsecurity.com/feed/"], "site": "https://krebsonsecurity.com/", "tag": "Istraživanja cyber kriminala, prevara i curenja podataka"},
    {"rank": 6,  "name": "The Hacker News",      "feeds": ["https://feeds.feedburner.com/TheHackersNews", "https://thehackernews.com/feeds/posts/default"], "site": "https://thehackernews.com/", "tag": "Napadi, malver i ranjivosti"},
    {"rank": 7,  "name": "Help Net Security",    "feeds": ["https://www.helpnetsecurity.com/feed/"], "site": "https://www.helpnetsecurity.com/", "tag": "Enterprise trendovi, regulativa i istraživanja"},
    {"rank": 8,  "name": "CyberScoop",           "feeds": ["https://cyberscoop.com/feed/"], "site": "https://cyberscoop.com/", "tag": "Državna bezbednost, politika i međunarodni cyber događaji"},
    {"rank": 9,  "name": "Infosecurity Magazine","feeds": ["https://www.infosecurity-magazine.com/rss/news/"], "site": "https://www.infosecurity-magazine.com/", "tag": "Vesti, analize, intervjui i istraživanja"},
    {"rank": 10, "name": "SC Media",             "feeds": ["https://www.scworld.com/feed", "https://www.scworld.com/rss.xml"], "site": "https://www.scworld.com/", "tag": "CISO teme, compliance, cloud i upravljanje rizicima"},
    {"rank": 11, "name": "Risky Business News",  "feeds": ["https://risky.biz/feeds/risky-business-news/"], "site": "https://news.risky.biz/", "tag": "Dnevni pregled cyber događaja i istraživanja"},
    {"rank": 12, "name": "CSO Online",           "feeds": ["https://www.csoonline.com/feed/"], "site": "https://www.csoonline.com/", "tag": "Strategija, leadership, budžeti i regulativa"},
    {"rank": 13, "name": "Security Affairs",     "feeds": ["https://securityaffairs.com/feed"], "site": "https://securityaffairs.com/", "tag": "APT grupe, malver, ranjivosti i incidenti"},
    {"rank": 14, "name": "Cybersecurity Dive",   "feeds": ["https://www.cybersecuritydive.com/feeds/news/"], "site": "https://www.cybersecuritydive.com/", "tag": "Poslovni uticaj incidenata, regulativa i strategija"},
    {"rank": 15, "name": "BankInfoSecurity",     "feeds": ["https://www.bankinfosecurity.com/rssFeeds.php?type=main"], "site": "https://www.bankinfosecurity.com/", "tag": "Finansijski sektor, prevare, identitet i zaštita podataka"},
    {"rank": 16, "name": "Cybernews",            "feeds": ["https://cybernews.com/feed/", "https://cybernews.com/security/feed/"], "site": "https://cybernews.com/security/", "tag": "Data breach događaji, privatnost i cybercrime"},
    {"rank": 17, "name": "TechCrunch Security",  "feeds": ["https://techcrunch.com/category/security/feed/"], "site": "https://techcrunch.com/category/security/", "tag": "Tehnološke kompanije, cloud i startup incidenti"},
    {"rank": 18, "name": "WIRED Security",       "feeds": ["https://www.wired.com/feed/category/security/latest/rss"], "site": "https://www.wired.com/category/security/", "tag": "Privatnost, nadzor i veliki incidenti"},
    {"rank": 19, "name": "Ars Technica Security","feeds": ["https://arstechnica.com/security/feed/"], "site": "https://arstechnica.com/security/", "tag": "Tehničke analize ranjivosti, napada i platformi"},
    {"rank": 20, "name": "CISA",                 "feeds": ["https://www.cisa.gov/cybersecurity-advisories/all.xml"], "site": "https://www.cisa.gov/news-events/cybersecurity-advisories", "tag": "Autoritativna upozorenja i preporučene mere"},
]

MAX_PER_SOURCE = 12           # koliko najnovijih stavki uzimamo po portalu
MAX_TOTAL = 150                # gornja granica ukupnog broja vesti na sajtu
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
    return "Vest"


def fetch_source(source: dict) -> list:
    items = []
    for feed_url in source["feeds"]:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as exc:
            print(f"  [!] {source['name']}: greška pri parsiranju {feed_url}: {exc}")
            continue

        if not parsed.entries:
            print(f"  [!] {source['name']}: feed {feed_url} nije dao rezultate, probam sledeći...")
            continue

        for entry in parsed.entries[:MAX_PER_SOURCE]:
            title = clean_text(entry.get("title", "")).strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            summary = clean_text(entry.get("summary", entry.get("description", "")))
            if len(summary) > SUMMARY_MAX_LEN:
                summary = summary[:SUMMARY_MAX_LEN].rsplit(" ", 1)[0] + "…"
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
            })
        if items:
            break  # ovaj kandidat je uspeo, ne probaj ostale adrese za ovaj izvor
    if not items:
        print(f"  [!] {source['name']}: nijedan RSS izvor nije dao rezultate.")
    return items


def dedupe(items: list) -> list:
    """Kad su dve vesti iz različitih izvora dovoljno slične po naslovu,
    zadrži samo onu sa portala nižeg (boljeg) ranga sa liste. Poredi se
    samo unutar prozora od nekoliko dana, jer ista vest o istom događaju
    izlazi na različitim portalima u kratkom vremenskom razmaku."""
    kept = []
    for item in sorted(items, key=lambda x: x["rank"]):
        item_dt = datetime.fromisoformat(item["timestamp"])
        is_dup = False
        for existing in kept:
            existing_dt = datetime.fromisoformat(existing["timestamp"])
            if abs((item_dt - existing_dt).total_seconds()) > 4 * 24 * 3600:
                continue
            if titles_are_duplicates(item["title"], existing["title"]):
                is_dup = True
                break
        if not is_dup:
            kept.append(item)
    return kept


def build_html(news: list) -> str:
    template_path = Path(__file__).parent / "template.html"
    template = template_path.read_text(encoding="utf-8")

    news_json = json.dumps(news, ensure_ascii=False, indent=2)
    sources_json = json.dumps(
        [{"rank": s["rank"], "name": s["name"], "url": s["site"], "tag": s["tag"]} for s in SOURCES],
        ensure_ascii=False, indent=2,
    )
    generated_at = datetime.now(timezone.utc).strftime("%d.%m.%Y. %H:%M UTC")

    out = template.replace("__NEWS_JSON__", news_json)
    out = out.replace("__SOURCES_JSON__", sources_json)
    out = out.replace("__GENERATED_AT__", generated_at)
    return out


def main():
    all_items = []
    print("Povlačim vesti sa 20 portala...")
    for source in SOURCES:
        print(f"- {source['name']}")
        items = fetch_source(source)
        print(f"    -> {len(items)} stavki")
        all_items.extend(items)

    print(f"\nUkupno pre deduplikacije: {len(all_items)}")
    deduped = dedupe(all_items)
    print(f"Nakon deduplikacije: {len(deduped)}")

    deduped.sort(key=lambda x: x["timestamp"], reverse=True)
    deduped = deduped[:MAX_TOTAL]

    out_dir = Path(__file__).parent / "docs"
    out_dir.mkdir(exist_ok=True)

    (out_dir / "index.html").write_text(build_html(deduped), encoding="utf-8")
    (out_dir / "news.json").write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nGenerisano: {out_dir / 'index.html'} ({len(deduped)} vesti)")


if __name__ == "__main__":
    main()
