#!/usr/bin/env python3
"""Aşama 3, çalışma anında yönlendirme (ağırlığa dokunmadan): seçilen katmanların çıkışında "kötü" yön u bastırılır.
İki kip: iz (izdüşümü sil: h <- h - a (h·u) u) ve kaydir (h <- h - b u). Tüm istem kümesi (araç isteyen, araçsız) yeniden
koşulur; araç çağrısı sayıları ve metin kalitesi karşılaştırılır.
    ../.venv/bin/python 03_yonlendir.py --katman 20,24 --kip iz --a 1.0
Çıktı: cikti/03_<kip>_<katmanlar>_<a>.json"""
import argparse
import json
import time

import mlx.core as mx
import numpy as np

from ortak import ARAC_ISTEMEYEN, ARAC_ISTEYEN, CIKTI, OnEk, arac_cagrilari, istem, katmanlari_coz, katmanlari_sar, model_yukle, uret

KATMAN_YOLU = lambda model: model.language_model.model.layers  # noqa: E731


def yonlendir(katmanlar, yonler, secili, kip, a):
    islevler = {}
    for l in secili:
        u = mx.array(yonler[l].astype(np.float32))

        def f(out, _u=u):
            o = out.astype(mx.float32)
            if kip == "iz":
                return (o - a * (o @ _u)[..., None] * _u).astype(out.dtype)
            return (o - a * _u).astype(out.dtype)
        islevler[l] = f
    return katmanlari_sar(katmanlar, islevler)


def geri_al(katmanlar, asil):
    katmanlari_coz(katmanlar, asil)


def kos(model, tokenizer, onek, etiketli, baslik):
    sonuc = []
    t = time.time()
    for grup, soru in etiketli:
        cikti = uret(model, tokenizer, istem(tokenizer, soru), en_cok=120, onek=onek)
        sonuc.append({"grup": grup, "soru": soru, "arac": [c.get("name") for c in arac_cagrilari(cikti)], "cikti": cikti[:300]})
    a = [s for s in sonuc if s["grup"] == "arac"]
    d = [s for s in sonuc if s["grup"] == "duz"]
    print(f"{baslik}: araç isteyen {len(a)} istemde {sum(1 for s in a if s['arac'])} araç çağrısı; araçsız {len(d)} istemde "
          f"{sum(1 for s in d if s['arac'])} gereksiz çağrı ({time.time() - t:.0f} sn)")
    return sonuc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--katman", default="")
    p.add_argument("--kip", default="iz", choices=["iz", "kaydir"])
    p.add_argument("--a", type=float, default=1.0)
    p.add_argument("--temel", action="store_true", help="yönlendirmesiz temel koşumu da yap")
    arg = p.parse_args()
    y = np.load(CIKTI / "02_yonler.npz")
    yonler, ayrisma = y["yonler"], y["ayrisma"]
    secili = [int(k) for k in arg.katman.split(",") if k.strip()] or [int(l) for l in np.argsort(ayrisma)[::-1][:3]]
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    kotu = [s for s, e in zip(ozet["istemler"], ozet["etiket"]) if e == "kotu"]
    model, tokenizer = model_yukle()
    katmanlar = KATMAN_YOLU(model)
    onek = OnEk(model, tokenizer, istem(tokenizer, ARAC_ISTEYEN[0]), ARAC_ISTEYEN[0])
    etiketli = [("arac", s) for s in ozet["istemler"]] + [("duz", s) for s in ARAC_ISTEMEYEN]
    if arg.temel:
        kos(model, tokenizer, onek, etiketli, "temel")
    asil = yonlendir(katmanlar, yonler, secili, arg.kip, arg.a)
    try:
        sonuc = kos(model, tokenizer, onek, etiketli, f"yönlendirme {arg.kip} katman {secili} a={arg.a}")
    finally:
        geri_al(katmanlar, asil)
    kotu_simdi = [s for s in sonuc if s["soru"] in kotu]
    print(f"  önceki kötü {len(kotu)} istemin {sum(1 for s in kotu_simdi if s['arac'])}'i artık araç çağırıyor")
    for s in kotu_simdi:
        print(f"    {'ARAÇ' if s['arac'] else 'yok '} | {s['soru'][:45]:<45} | {s['cikti'][:70].replace(chr(10), ' ')}")
    print("  araçsız sorular:")
    for s in sonuc:
        if s["grup"] == "duz":
            print(f"    {'ARAÇ!' if s['arac'] else 'metin'} | {s['soru'][:40]:<40} | {s['cikti'][:80].replace(chr(10), ' ')}")
    ad = f"03_{arg.kip}_{'-'.join(map(str, secili))}_{arg.a}.json"
    (CIKTI / ad).write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
