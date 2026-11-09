#!/usr/bin/env python3
"""Hakem isteği: oranlar için Wilson %95 güven aralıkları ve eşleştirilmiş karşılaştırmalar için McNemar testi (tam binom).
Veriler: 11_*.json (98 istem, 60 regresyon), 06_sonuc.json ve 10_ema2.json (68 geliştirme, 40 sınama).
Çıktı: cikti/14_istatistik.md"""
import json
from math import comb, sqrt

from ortak import CIKTI


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    merkez = (p + z * z / (2 * n)) / (1 + z * z / n)
    yarim = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, merkez - yarim), min(1.0, merkez + yarim))


def mcnemar(b, c):
    """b: yalnız birincide başarılı, c: yalnız ikincide başarılı. İki yönlü tam binom p değeri."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n * 2
    return min(1.0, p)


def ayrinti(ad):
    return json.loads((CIKTI / f"11_{ad}.json").read_text(encoding="utf-8"))


def esle(a, b, anahtar="arac"):
    """Aynı sırada iki ayrıntı listesi: (yalnız a, yalnız b, ikisi de, hiçbiri)."""
    ya = yb = ikisi = hic = 0
    for x, y in zip(a, b):
        assert x["soru"] == y["soru"]
        if x[anahtar] and not y[anahtar]:
            ya += 1
        elif y[anahtar] and not x[anahtar]:
            yb += 1
        elif x[anahtar]:
            ikisi += 1
        else:
            hic += 1
    return ya, yb, ikisi, hic


def satir_ga(etiket, k, n):
    a, b = wilson(k, n)
    return f"| {etiket} | {k}/{n} | {100 * k / n:.1f} | [{100 * a:.1f}, {100 * b:.1f}] |"


def main():
    import importlib
    import re
    s11 = importlib.import_module("11_saglamlik")
    desen = {soru: d for soru, d in s11.REGRESYON}
    temel, silme, itme, ornek = (ayrinti(a) for a in ("temel", "silme_ema1", "itme_ema2", "temel_orneklerle"))
    for d in (temel, silme, itme, ornek):
        for r in d["regresyon"]:
            r["dogru2"] = bool(re.search(desen[r["soru"]], r["cevap"].lower()))
    cikti = ["## Wilson %95 güven aralıkları", "", "| Ölçüm | k/n | % | %95 GA |", "|---|---|---|---|"]
    gel = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))
    d10 = json.loads((CIKTI / "10_ema2.json").read_text(encoding="utf-8"))
    for etiket, k, n in [
        ("Temel, geliştirme (68)", gel["temel"]["gelistirme"]["arac_cagri"], 68),
        ("Silme a=1,5 çalışma anı, geliştirme (68)", gel["V1 silme a=1.5"]["gelistirme"]["arac_cagri"], 68),
        ("İtme derlenmiş, geliştirme (68)", d10["gelistirme"]["arac_cagri"], 68),
        ("Temel, sınama (40)", gel["temel"]["sinama"]["arac_cagri"], 40),
        ("Silme a=1,5 çalışma anı, sınama (40)", gel["V1 silme a=1.5"]["sinama"]["arac_cagri"], 40),
        ("İtme derlenmiş, sınama (40)", d10["sinama"]["arac_cagri"], 40),
        ("Temel, büyük sınama (98)", temel["buyuk"][0]["arac"], 98),
        ("Silme derlenmiş, büyük sınama (98)", silme["buyuk"][0]["arac"], 98),
        ("İtme derlenmiş, büyük sınama (98)", itme["buyuk"][0]["arac"], 98),
        ("Beş örnekli talimat, büyük sınama (98)", ornek["buyuk"][0]["arac"], 98),
        ("Temel, regresyon (60)", sum(r["dogru2"] for r in temel["regresyon"]), 60),
        ("Silme derlenmiş, regresyon (60)", sum(r["dogru2"] for r in silme["regresyon"]), 60),
        ("İtme derlenmiş, regresyon (60)", sum(r["dogru2"] for r in itme["regresyon"]), 60),
    ]:
        cikti.append(satir_ga(etiket, k, n))
    cikti += ["", "## McNemar (eşleştirilmiş, iki yönlü tam binom)", "", "| Karşılaştırma | yalnız 1. | yalnız 2. | ikisi | hiçbiri | p |", "|---|---|---|---|---|---|"]
    bt, bs, bi, bo = (d["buyuk"][0]["ayrinti"] for d in (temel, silme, itme, ornek))
    bt = [x for x in bt if x["grup"] == "arac"]; bs = [x for x in bs if x["grup"] == "arac"]; bi = [x for x in bi if x["grup"] == "arac"]; bo = [x for x in bo if x["grup"] == "arac"]
    for etiket, a, b in [("Temel vs itme, büyük sınama (98)", bt, bi), ("Temel vs silme, büyük sınama (98)", bt, bs),
                         ("Beş örnekli talimat vs itme, büyük sınama (98)", bo, bi), ("Silme vs itme, büyük sınama (98)", bs, bi)]:
        ya, yb, ikisi, hic = esle(a, b)
        cikti.append(f"| {etiket} | {ya} | {yb} | {ikisi} | {hic} | {mcnemar(ya, yb):.4f} |")
    for etiket, a, b in [("Temel vs itme, regresyon (60)", temel["regresyon"], itme["regresyon"]), ("Temel vs silme, regresyon (60)", temel["regresyon"], silme["regresyon"])]:
        ya, yb, ikisi, hic = esle(a, b, "dogru2")
        cikti.append(f"| {etiket} | {ya} | {yb} | {ikisi} | {hic} | {mcnemar(ya, yb):.4f} |")
    # geliştirme 68: temel vs itme derlenmiş (06 temel ayrıntısı ile 10 ayrıntısı aynı sırada)
    g_t = [x for x in gel["temel"]["gelistirme"]["ayrinti"] if x["grup"] == "arac"]
    g_i = [x for x in d10["gelistirme"]["ayrinti"] if x["grup"] == "arac"]
    g_s = [x for x in gel["V1 silme a=1.5"]["gelistirme"]["ayrinti"] if x["grup"] == "arac"]
    for etiket, a, b in [("Temel vs itme derlenmiş, geliştirme (68)", g_t, g_i), ("Temel vs silme a=1,5, geliştirme (68)", g_t, g_s)]:
        ya, yb, ikisi, hic = esle(a, b)
        cikti.append(f"| {etiket} | {ya} | {yb} | {ikisi} | {hic} | {mcnemar(ya, yb):.4f} |")
    metin = "\n".join(cikti)
    print(metin)
    (CIKTI / "14_istatistik.md").write_text(metin + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
