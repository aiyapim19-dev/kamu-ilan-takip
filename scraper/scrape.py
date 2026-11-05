#!/usr/bin/env python3
"""Kamu işe alım ilanlarını kontrol eder, yenileri docs/data/ilanlar.json'a yazar
ve (NTFY_TOPIC tanımlıysa) telefona bildirim gönderir.

Her kaynak ayrı ayrı denenir; biri bozulsa diğerleri çalışmaya devam eder.
Kaynak durumu uygulamada görünür. robots.txt izin vermeyen sayfalar atlanır.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data", "ilanlar.json")
SOURCES = os.path.join(ROOT, "scraper", "sources.json")
UA = "KamuIlanTakip/1.0 (kisisel kullanim; saatte bir kontrol)"
TZ = dt.timezone(dt.timedelta(hours=3))
KEEP_DAYS = 45
MAX_ITEMS = 600

INCLUDE = [
    "alım", "alim", "alınacak", "alacak", "personel", "memur", "işçi", "sözleşmeli",
    "öğretim", "uzman", "zabıta", "itfaiye", "sınav", "kadro", "temin", "engelli",
    "bekçi", "güvenlik görevlisi", "tekniker", "mühendis", "hekim", "hemşire",
]
EXCLUDE = [
    "ihale", "satış", "kiralama", "icra", "haciz", "ihtar", "ödeme emri", "imar",
    "sonuç", "iptal", "ertelen", "gizlilik", "çerez", "kvkk",
]
KURUM_RE = re.compile(
    r"(üniversitesi|belediye|bakanlığ|başkanlığ|müdürlüğ|kurumu|valiliği|kaymakamlığ|"
    r"hastane|birliği|odası|akademi|a\.ş)"
)
KURUM_PREFIX = re.compile(
    r"^(.{3,100}?(üniversitesi|belediye başkanlığı|belediyesi|bakanlığı|başkanlığı|"
    r"genel müdürlüğü|müdürlüğü|valiliği|kaymakamlığı|hastanesi|birliği|odası|"
    r"rektörlüğü|dekanlığı|başhekimliği|kurumu))"
)
# Menü/kategori bağlantılarını ele: "...Nedir ?", "Kamu-Akademik Personel (119)", "PERSONEL ALIMI 119"
TITLE_EXCLUDE_RE = [re.compile(p) for p in (r"\?\s*$", r"\(\d+\)\s*$", r"\s\d{1,4}\s*$")]
TR_MAP = str.maketrans({"İ": "i", "I": "ı"})


def low(s):
    return s.translate(TR_MAP).lower()


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def now_iso():
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


# ----------------------------------------------------------------- fetching
_robots = {}


def robots_allowed(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=15)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp.parse([])  # robots.txt yok -> serbest
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return rp.can_fetch(UA, url)


def fetch_static(url):
    r = requests.get(
        url,
        headers={"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"},
        timeout=30,
    )
    r.raise_for_status()
    if r.encoding in (None, "ISO-8859-1"):
        r.encoding = r.apparent_encoding
    return r.text


def fetch_js(url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=UA, locale="tr-TR")
            page.goto(url, wait_until="networkidle", timeout=45000)
            return page.content()
        finally:
            browser.close()


# --------------------------------------------------------------- extraction
def extract(html, base_url, cfg=None):
    cfg = cfg or {}
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header"]):
        t.decompose()
    include = [low(x) for x in cfg.get("include", INCLUDE)]
    exclude = [low(x) for x in cfg.get("exclude", EXCLUDE)]
    keep_all = cfg.get("keep_all", False)
    found, seen = [], set()
    for a in soup.select(cfg.get("selector", "a[href]")):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        title = norm(a.get_text(" "))
        row = a.find_parent(["tr", "li", "article"])
        cells = []
        if row is not None and row.name == "tr":
            cells = [norm(c.get_text(" ")) for c in row.find_all(["td", "th"])]
        context = norm(row.get_text(" ")) if row is not None else title
        if len(title.split()) < 3 and cells:
            # kısa link metni ("Detay" gibi) -> satırdaki en uzun hücreyi başlık yap
            longest = max(cells, key=len, default="")
            if len(longest.split()) >= 3:
                title = longest
        if len(title.split()) < 3 or len(title) > 300:
            continue
        if any(r.search(title) for r in TITLE_EXCLUDE_RE):
            continue
        hay = low(title + " " + context)
        if any(x in hay for x in exclude):
            continue
        if not keep_all and not any(x in hay for x in include):
            continue
        url = urljoin(base_url, href)
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        found.append({"baslik": title, "url": url, "kurum": guess_kurum(title, cells)})
    return found


def guess_kurum(title, cells):
    for c in cells:
        if c != title and len(c) < 120 and KURUM_RE.search(low(c)):
            return c
    # low() karakter sayısını korur, bu yüzden indeksler orijinal başlıkla örtüşür
    m = KURUM_PREFIX.match(low(title))
    return title[: m.end(1)].strip() if m else ""


def discover(html, base_url, terms):
    """Ana sayfadaki bağlantılardan, metni terimlerden birini içerenleri bulur."""
    soup = BeautifulSoup(html, "html.parser")
    terms = [low(t) for t in terms]
    out = []
    for a in soup.select("a[href]"):
        if any(t in low(norm(a.get_text(" "))) for t in terms):
            u = urljoin(base_url, a["href"].strip())
            if u.startswith("http") and u not in out:
                out.append(u)
    return out[:4]


def item_id(source, it):
    raw = f"{source}|{it['url']}|{it['baslik']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ sources
def get_page(url, cfg):
    return fetch_js(url) if cfg.get("js") else fetch_static(url)


def run_source(cfg):
    today = dt.datetime.now(TZ).strftime("%Y-%m-%d")
    candidates = [u.replace("{date}", today) for u in cfg.get("urls", [cfg.get("url")])]
    st = {"id": cfg["id"], "name": cfg["name"], "url": candidates[0], "ok": False,
          "count": 0, "error": "", "checked": now_iso()}
    try:
        html, url, last_err = None, None, None
        for cand in candidates:
            if not robots_allowed(cand):
                last_err = "Sitenin robots.txt dosyası otomatik erişime izin vermiyor, atlandı"
                continue
            try:
                html, url = get_page(cand, cfg), cand
                st["url"] = cand
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {str(e)[:160]}"
        if html is None:
            st["error"] = last_err or "Sayfa açılamadı"
            return st, []
        if cfg.get("follow"):
            links = [u for u in discover(html, url, cfg["follow"]) if robots_allowed(u)]
            if not links:
                st["error"] = "Ana sayfada ilgili bağlantı bulunamadı"
                return st, []
            items = []
            for link in links:
                try:
                    items += extract(get_page(link, cfg), link, cfg)
                except Exception as e:  # noqa: BLE001
                    st["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        else:
            items = extract(html, url, cfg)
        st["ok"] = True
        st["count"] = len(items)
        if not items:
            st["error"] = "Sayfa açıldı ama ilan bulunamadı (sayfa yapısı farklı olabilir)"
        for it in items:
            it["source"] = cfg["id"]
            it["id"] = item_id(cfg["id"], it)
        return st, items
    except Exception as e:  # noqa: BLE001
        st["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return st, []


# ------------------------------------------------------------------- notify
def notify(new_items, names):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic or not new_items:
        return
    click = os.environ.get("APP_URL", "").strip() or None
    shown = new_items[:5]
    msgs = []
    for it in shown:
        kurum = it.get("kurum") or names.get(it["source"], "")
        msgs.append({"topic": topic, "title": f"🚨 Yeni ilan: {kurum}"[:120],
                     "message": it["baslik"][:300], "priority": 4,
                     "tags": ["rotating_light"], "click": it["url"]})
    if len(new_items) > len(shown):
        msgs.append({"topic": topic, "title": f"{len(new_items)} yeni ilan var",
                     "message": f"+{len(new_items) - len(shown)} ilan daha. Uygulamayı aç.",
                     "priority": 3, "tags": ["bell"], "click": click})
    for m in msgs:
        if click and "click" not in m:
            m["click"] = click
        try:
            requests.post("https://ntfy.sh/", json=m, timeout=20)
        except Exception as e:  # noqa: BLE001
            print("bildirim gönderilemedi:", e, file=sys.stderr)


# --------------------------------------------------------------------- main
def merge(state, results, now):
    """results: [(status, items)]. Yeni ilanları döndürür, state'i günceller."""
    existing = {it["id"]: it for it in state.get("items", [])}
    seeded = set(state.get("seeded", []))
    new_items = []
    for st, items in results:
        if not st["ok"] or not items:
            continue
        first_run = st["id"] not in seeded
        for it in items:
            if it["id"] in existing:
                continue
            rec = {"id": it["id"], "source": it["source"], "kurum": it["kurum"],
                   "baslik": it["baslik"], "url": it["url"], "first_seen": now}
            if first_run:
                rec["seed"] = True  # ilk taramadaki mevcut ilanlar "yeni" sayılmaz
            else:
                new_items.append(rec)
            existing[rec["id"]] = rec
        seeded.add(st["id"])
    cutoff = (dt.datetime.fromisoformat(now) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    kept = [i for i in existing.values() if i["first_seen"] >= cutoff]
    kept.sort(key=lambda i: i["first_seen"], reverse=True)
    state["items"] = kept[:MAX_ITEMS]
    state["seeded"] = sorted(seeded)
    return new_items


def main():
    sources = json.load(open(SOURCES, encoding="utf-8"))
    try:
        state = json.load(open(DATA, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"items": [], "seeded": []}
    results = []
    for cfg in sources:
        st, items = run_source(cfg)
        print(f"[{'OK ' if st['ok'] else 'ERR'}] {cfg['name']}: {st['count']} ilan {st['error']}")
        results.append((st, items))
    now = now_iso()
    new_items = merge(state, results, now)
    state["updated"] = now
    state["sources"] = [r[0] for r in results]
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    notify(new_items, {s["id"]: s["name"] for s in sources})
    print(f"Yeni ilan: {len(new_items)}")


if __name__ == "__main__":
    main()
