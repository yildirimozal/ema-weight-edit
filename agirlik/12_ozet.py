#!/usr/bin/env python3
"""11_*.json dosyalarını (sağlamlık ölçümleri) tek tabloda özetler; regresyon cevapları güncel desenlerle yeniden puanlanır
(ilk koşumda "300.000" gibi binlik ayraçlı sayılar desene uymuyordu). Çıktı: cikti/12_tablo.md"""
import importlib, json, re
from ortak import CIKTI
s11 = importlib.import_module("11_saglamlik")
desen = {soru: d for soru, d in s11.REGRESYON}
satirlar = ["| Model | Regresyon doğru (60) | Gereksiz araç (60 soru) | Büyük sınama araç (98), tekrarlar | Gereksiz (20 düz), tekrarlar |", "|---|---|---|---|---|"]
for ad in ("temel", "silme_ema1", "itme_ema2", "temel_orneklerle"):
    f = CIKTI / f"11_{ad}.json"
    if not f.exists():
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    dogru = sum(1 for r in d["regresyon"] if re.search(desen[r["soru"]], r["cevap"].lower()))
    gereksiz = sum(r["arac"] for r in d["regresyon"])
    buyuk = ", ".join(f"{b['arac']}/{b['arac_toplam']}" for b in d["buyuk"])
    duz = ", ".join(f"{b['gereksiz']}/{b['duz_toplam']}" for b in d["buyuk"])
    satirlar.append(f"| {ad} | {dogru}/60 | {gereksiz} | {buyuk} | {duz} |")
metin = "\n".join(satirlar)
print(metin)
(CIKTI / "12_tablo.md").write_text(metin + "\n", encoding="utf-8")
