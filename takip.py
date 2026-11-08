"""Finnhub hisse takibi: veriyi çeker, günlük geçmişe ekler, dashboard.html üretir.

Kullanım:  python takip.py          (normal çalışma)
           python takip.py --html   (son veriden yalnızca sayfayı yeniden üret)
           python takip.py --test   (puanlama öz-testi, API çağrısı yok)
"""
import json, sys, time, datetime, webbrowser, urllib.request, urllib.parse
from pathlib import Path

KOK = Path(__file__).parent
API = "https://finnhub.io/api/v1"
GECMIS = KOK / "gecmis.json"
LOG = KOK / "calisma.log"


def log(msg):
    satir = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(satir)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(satir + "\n")


def api(yol, anahtar, **params):
    params["token"] = anahtar
    url = f"{API}/{yol}?{urllib.parse.urlencode(params)}"
    for deneme in range(3):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:  # ücretsiz plan: dakikada 60 istek
                time.sleep(20)
                continue
            if e.code in (401, 403):
                raise SystemExit(f"Finnhub erişimi reddedildi ({e.code}) – {yol}. API anahtarını kontrol et.")
            return None
        except OSError:
            time.sleep(3)
    return None


def bilesenler(oneri, getiri_13h):
    """Puanın iki parçası, her biri 0-100: analist konsensüsü ve 13 haftalık momentum."""
    analist = None
    if oneri:
        toplam = oneri["strongBuy"] + oneri["buy"] + oneri["hold"] + oneri["sell"] + oneri["strongSell"]
        if toplam:
            ham = (2 * oneri["strongBuy"] + oneri["buy"] - oneri["sell"] - 2 * oneri["strongSell"]) / toplam
            analist = (ham + 2) / 4 * 100
    momentum = None if getiri_13h is None else (max(-30, min(30, getiri_13h)) + 30) / 60 * 100
    return analist, momentum


def yahoo_seri(sembol):
    """Yahoo Finance'ten 1 yıllık günlük kapanışlar: {tarih: kapanış}. Finnhub ücretsiz plan BIST/emtia vermiyor.
    shortcut: resmi olmayan Yahoo uç noktası, bozulursa bu bölüm boş kalır; kalıcı çözüm ücretli bir veri kaynağı."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sembol)}?range=1y&interval=1d"
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for _ in range(2):
        try:
            with urllib.request.urlopen(istek, timeout=20) as r:
                s = json.load(r)["chart"]["result"][0]
            kapanis = s["indicators"]["quote"][0]["close"]
            return {str(datetime.date.fromtimestamp(t)): c for t, c in zip(s["timestamp"], kapanis) if c is not None}
        except (OSError, KeyError, IndexError, TypeError, ValueError):
            time.sleep(2)
    return {}


def seri_ozet(sembol, ad, seri, para):
    """Kapanış serisinden kart/tablo için özet: son fiyat, getiriler, 52 hafta aralığı, 3 aylık seyir."""
    if len(seri) < 2:
        return {"sembol": sembol, "ad": ad, "para": para, "fiyat": None}
    g = sorted(seri)
    k = [seri[t] for t in g]
    getiri = lambda n: (k[-1] / k[-1 - n] - 1) * 100 if len(k) > n else None
    return {
        "sembol": sembol, "ad": ad, "para": para, "fiyat": k[-1], "tarih": g[-1],
        "degisim_yuzde": getiri(1), "getiri_1a": getiri(21), "getiri_3a": getiri(63),
        "getiri_1y": (k[-1] / k[0] - 1) * 100,
        "yuksek": max(k), "dusuk": min(k),
        "seyir": [round(x, 4) for x in k[-63:]],
    }


def piyasalar(ayar):
    madenler, bist = [], []
    seriler = {}
    for s, ad in ayar.get("madenler", {}).items():
        seriler[s] = yahoo_seri(s)
        time.sleep(0.4)
        madenler.append(seri_ozet(s, ad, seriler[s], "TRY" if s.endswith("TRY=X") else "USD"))
    ons, kur = seriler.get("GC=F", {}), seriler.get("USDTRY=X", {})
    if ons and kur:  # gram altın = ons $ × USD/TRY ÷ 31,1035 (aynı günlerin kapanışı)
        gram = {t: ons[t] * kur[t] / 31.1035 for t in ons if t in kur}
        madenler.insert(0, seri_ozet("GRAM", "Gram altın", gram, "TRY"))
    for s, ad in ayar.get("bist", {}).items():
        bist.append(seri_ozet(s.removesuffix(".IS"), ad, yahoo_seri(s), "TRY"))
        time.sleep(0.4)
    return madenler, bist


def puan(oneri, getiri_13h):
    """0-100 sinyal puanı: %60 analist konsensüsü + %40 son 13 hafta momentumu."""
    analist, momentum = bilesenler(oneri, getiri_13h)
    if analist is None and momentum is None:
        return None
    if analist is None:
        return round(momentum)
    if momentum is None:
        return round(analist)
    return round(0.6 * analist + 0.4 * momentum)


def etiket(p):
    if p is None:
        return "Veri yok"
    # büyük şirketlerde analistler hep olumlu; eşikler o yüzden yüksek
    return "Güçlü sinyal" if p >= 75 else "İzle" if p >= 60 else "Zayıf"


def hisse_topla(sembol, anahtar):
    bugun = datetime.date.today()
    q = api("quote", anahtar, symbol=sembol) or {}
    time.sleep(1.1)
    profil = api("stock/profile2", anahtar, symbol=sembol) or {}
    time.sleep(1.1)
    oneriler = api("stock/recommendation", anahtar, symbol=sembol) or []
    time.sleep(1.1)
    metrik = (api("stock/metric", anahtar, symbol=sembol, metric="all") or {}).get("metric", {})
    time.sleep(1.1)
    haber = api("company-news", anahtar, symbol=sembol,
                **{"from": str(bugun - datetime.timedelta(days=3)), "to": str(bugun)}) or []
    time.sleep(1.1)

    oneri = oneriler[0] if oneriler else None
    g13 = metrik.get("13WeekPriceReturnDaily")
    p = puan(oneri, g13)
    analist, momentum = bilesenler(oneri, g13)
    return {
        "analist_puan": analist and round(analist),
        "momentum_puan": momentum and round(momentum),
        "sembol": sembol,
        "ad": profil.get("name") or sembol,
        "sektor": profil.get("finnhubIndustry"),
        "logo": profil.get("logo"),
        "piyasa_degeri": profil.get("marketCapitalization"),  # milyon $
        "fiyat": q.get("c"),
        "degisim_yuzde": q.get("dp"),
        "gun_yuksek": q.get("h"),
        "gun_dusuk": q.get("l"),
        "hafta52_yuksek": metrik.get("52WeekHigh"),
        "hafta52_dusuk": metrik.get("52WeekLow"),
        "getiri_13h": g13,
        "getiri_52h": metrik.get("52WeekPriceReturnDaily"),
        "fk": metrik.get("peTTM"),
        "beta": metrik.get("beta"),
        "temettu": metrik.get("currentDividendYieldTTM"),
        "oneri": oneri,
        "puan": p,
        "etiket": etiket(p),
        "haberler": [{"baslik": h["headline"], "url": h["url"], "kaynak": h["source"], "zaman": h["datetime"]}
                     for h in sorted(haber, key=lambda h: -h.get("datetime", 0))[:3]],
    }


def calistir():
    anahtar_dosya = KOK / "api_key.txt"
    if not anahtar_dosya.exists() or not anahtar_dosya.read_text().strip():
        raise SystemExit("api_key.txt bulunamadı ya da boş. Finnhub API anahtarını bu dosyaya yapıştır.")
    anahtar = anahtar_dosya.read_text().strip()
    ayar = json.loads((KOK / "config.json").read_text(encoding="utf-8"))

    log(f"Başladı: {len(ayar['hisseler'])} hisse")
    hisseler = []
    for s in ayar["hisseler"]:
        try:
            hisseler.append(hisse_topla(s, anahtar))
        except SystemExit:
            raise
        except Exception as e:  # tek hissenin hatası tüm raporu durdurmasın
            log(f"{s} atlandı: {e}")
    piyasa_haber = (api("news", anahtar, category="general") or [])[:8]
    madenler, bist = piyasalar(ayar)

    gecmis = json.loads(GECMIS.read_text(encoding="utf-8")) if GECMIS.exists() else {}
    gecmis[str(datetime.date.today())] = {h["sembol"]: {"fiyat": h["fiyat"], "puan": h["puan"]} for h in hisseler}
    GECMIS.write_text(json.dumps(gecmis, ensure_ascii=False, indent=1), encoding="utf-8")

    veri = {
        "guncelleme": f"{datetime.datetime.now():%d.%m.%Y %H:%M}",
        "hisseler": sorted(hisseler, key=lambda h: -(h["puan"] or -1)),
        "gecmis": gecmis,
        "madenler": madenler,
        "bist": bist,
        "piyasa_haber": [{"baslik": h["headline"], "url": h["url"], "kaynak": h["source"]} for h in piyasa_haber],
    }
    (KOK / "son_veri.json").write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    html_uret(veri)
    log(f"Bitti: {len(hisseler)} hisse, dashboard.html güncellendi")
    if ayar.get("dashboard_ac", True):
        webbrowser.open((KOK / "dashboard.html").as_uri())


def html_uret(veri):
    sablon = (KOK / "sablon.html").read_text(encoding="utf-8")
    js = json.dumps(veri, ensure_ascii=False).replace("</", "<\\/")
    (KOK / "dashboard.html").write_text(sablon.replace("/*VERI*/null", js), encoding="utf-8")


def test():
    assert puan({"strongBuy": 10, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}, 30) == 100
    assert puan({"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 10}, -30) == 0
    assert puan({"strongBuy": 0, "buy": 0, "hold": 5, "sell": 0, "strongSell": 0}, 0) == 50
    assert puan(None, 90) == 100  # momentum ±30'a kırpılır
    assert puan(None, None) is None
    o = seri_ozet("X", "X", {f"2026-01-{i + 1:02d}": 100 + i for i in range(25)}, "TRY")
    assert o["fiyat"] == 124 and o["dusuk"] == 100 and abs(o["getiri_1y"] - 24) < 1e-9
    assert abs(o["degisim_yuzde"] - (124 / 123 - 1) * 100) < 1e-9 and o["getiri_3a"] is None
    assert seri_ozet("X", "X", {}, "USD")["fiyat"] is None
    assert etiket(75) == "Güçlü sinyal" and etiket(60) == "İzle" and etiket(59) == "Zayıf"
    print("test: tamam")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--html" in sys.argv:  # API'ye gitmeden son veriden sayfayı yeniden üret
        html_uret(json.loads((KOK / "son_veri.json").read_text(encoding="utf-8")))
    elif "--piyasa" in sys.argv:  # yalnızca maden/BIST verisini tazele (Finnhub'a gitmez)
        v = json.loads((KOK / "son_veri.json").read_text(encoding="utf-8"))
        v["madenler"], v["bist"] = piyasalar(json.loads((KOK / "config.json").read_text(encoding="utf-8")))
        (KOK / "son_veri.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        html_uret(v)
    else:
        calistir()
