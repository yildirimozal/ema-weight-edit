#!/usr/bin/env python3
"""Hakem istekleri (ikinci tur), çalışma anı kontrol deneyleri, temel modelde, geliştirme (68+8) ve sınama (40+8) kümelerinde:
(A) Konum taraması: artık akımda silme (a=1, v1, katman 27-29) istemin son konumunda ve ilk K üretilen tokende, K = 0, 1, 3, 10, hepsi.
(B) Rastgele yön kontrolü: aynı büyüklükte (b = 0.5·gap) itme ve (a = 1.5) silme, rastgele birim yönlerle; artı ters yönde itme (b = -0.5·gap).
(C) Kanal kararlılığı: 10 seçili kanal üzerinden gerçekleşen itmenin (Σ c_j x_j) seçim kümesi dışındaki istem kümelerinde token başına
    dağılımı (ortalama ve standart sapma, amaçlanan b'ye oranla): 98 araç istemi, 60 regresyon sorusu, 20 düz soru.
    ../.venv/bin/python 15_kontrol.py
Çıktı: cikti/15_kontrol.json, cikti/15_ozet.txt"""
import importlib
import json
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from ortak import ARAC_ISTEMEYEN, CIKTI, OnEk, arac_cagrilari, istem, model_yukle

y04 = importlib.import_module("04_karar_noktasi")
y06 = importlib.import_module("06_yon_varyantlari")
s11 = importlib.import_module("11_saglamlik")
KATMANLAR = [27, 28, 29]


def olc_sayacli(model, tokenizer, onek, kume, etiketler, yonlendirici):
    sonuc = []
    for (grup, soru), e in zip(kume, etiketler):
        c = y04.uret_sayacli(model, tokenizer, istem(tokenizer, soru), onek, yonlendirici, en_cok=120)
        sonuc.append({"grup": grup, "soru": soru, "temel": e, "arac": bool(arac_cagrilari(c)), "cikti": c[:200]})
    arac = [s for s in sonuc if s["grup"] == "arac"]
    duz = [s for s in sonuc if s["grup"] == "duz"]
    return {"arac_cagri": sum(s["arac"] for s in arac), "arac_toplam": len(arac),
            "duzelen": sum(1 for s in arac if s["temel"] == "kotu" and s["arac"]),
            "bozulan": sum(1 for s in arac if s["temel"] == "iyi" and not s["arac"]),
            "gereksiz": sum(s["arac"] for s in duz), "ayrinti": sonuc}


class ItmeKaydedici(nn.Module):
    """down_proj girişinde seçili kanalların katsayılı toplamını (token başına gerçekleşen itme) biriktirir."""

    def __init__(self, ic, kanallar, katsayilar):
        super().__init__()
        self.ic = ic
        self.kanallar = mx.array(np.asarray(kanallar, dtype=np.int32))
        self.katsayilar = mx.array(np.asarray(katsayilar, dtype=np.float32))
        self.degerler = []

    def __call__(self, x):
        xj = mx.take(x.astype(mx.float32).reshape(-1, x.shape[-1]), self.kanallar, axis=-1)
        v = xj @ self.katsayilar
        mx.eval(v)
        self.degerler.append(np.array(v))
        return self.ic(x)


def kanal_kararliligi(model, tokenizer, onek, katmanlar, secim, gap, kumeler):
    sonuc = {}
    for ad, istemler in kumeler.items():
        kayit = {l: ItmeKaydedici(katmanlar[l].mlp.down_proj, secim[str(l)]["kanallar"], secim[str(l)]["katsayilar"]) for l in KATMANLAR}
        for l in KATMANLAR:
            katmanlar[l].mlp.down_proj = kayit[l]
        try:
            for soru in istemler:
                model(mx.array(onek.kalan(tokenizer, istem(tokenizer, soru)))[None], cache=onek.kopya())
        finally:
            for l in KATMANLAR:
                katmanlar[l].mlp.down_proj = kayit[l].ic
        sonuc[ad] = {}
        for l in KATMANLAR:
            v = np.concatenate(kayit[l].degerler)
            b = 0.5 * gap[l]  # katsayılar -b itmesini verecek biçimde kuruldu: beklenen Σ c_j x_j ≈ -b... işaret 09'daki kurguya göre
            oran = v / b
            sonuc[ad][l] = {"token": int(len(v)), "ortalama_bolu_b": float(np.mean(oran)), "std_bolu_b": float(np.std(oran)),
                            "p10_bolu_b": float(np.percentile(oran, 10)), "p90_bolu_b": float(np.percentile(oran, 90))}
        print(f"  kanal kararlılığı {ad}: " + ", ".join(f"k{l} ort {sonuc[ad][l]['ortalama_bolu_b']:.2f} std {sonuc[ad][l]['std_bolu_b']:.2f}" for l in KATMANLAR))
    return sonuc


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--parca", default="hepsi", choices=["hepsi", "rastgele_kalan"], help="rastgele_kalan: yalnız rastgele silme ve ters itme (önceki kayıt korunur)")
    arg = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()
    model, tokenizer = model_yukle()
    katmanlar = y06.KATMAN_YOLU(model)
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    yon = np.load(CIKTI / "06_yonler.npz")
    v1, gap = yon["v1"], yon["gap"]
    temel06 = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))["temel"]
    gel = [(s["grup"], s["soru"]) for s in temel06["gelistirme"]["ayrinti"]]
    et_gel = [s["temel"] for s in temel06["gelistirme"]["ayrinti"]]
    sin = [(s["grup"], s["soru"]) for s in temel06["sinama"]["ayrinti"]]
    et_sin = [s["temel"] for s in temel06["sinama"]["ayrinti"]]
    onek = OnEk(model, tokenizer, istem(tokenizer, ozet["istemler"][0]), ozet["istemler"][0])
    print(f"hazır {time.time() - t0:.0f} sn; geliştirme {len(gel)}, sınama {len(sin)}")
    cikti = {"konum": {}, "rastgele": {}, "kanal": {}}
    satirlar = []
    if arg.parca == "rastgele_kalan":
        cikti = json.loads((CIKTI / "15_kontrol.json").read_text(encoding="utf-8"))
        satirlar = (CIKTI / "15_ozet.txt").read_text(encoding="utf-8").strip().split("\n")

    def kaydet():
        (CIKTI / "15_kontrol.json").write_text(json.dumps(cikti, ensure_ascii=False, indent=1), encoding="utf-8")
        (CIKTI / "15_ozet.txt").write_text("\n".join(satirlar) + "\n", encoding="utf-8")

    def satir_yaz(ad, g, s, t):
        satir = (f"{ad:<40} geliştirme {g['arac_cagri']}/{g['arac_toplam']} (düzelen {g['duzelen']}, bozulan {g['bozulan']}, gereksiz {g['gereksiz']}) | "
                 f"sınama {s['arac_cagri']}/{s['arac_toplam']} (düzelen {s['duzelen']}, bozulan {s['bozulan']}, gereksiz {s['gereksiz']}) [{time.time() - t:.0f} sn]")
        print(satir)
        satirlar.append(satir)

    # (C) önce: üretim gerektirmez, hızlı
    if arg.parca == "hepsi":
      secim = json.loads((CIKTI / "09_kanallar.json").read_text(encoding="utf-8"))["v1 itme 10 kanal b=0.5gap"]
      kumeler = {"secim_68": ozet["istemler"], "buyuk_arac_98": s11.BUYUK_ARAC, "regresyon_60": [q for q, _ in s11.REGRESYON], "duz_20": s11.BUYUK_DUZ}
      cikti["kanal"] = kanal_kararliligi(model, tokenizer, onek, katmanlar, secim, gap, kumeler)
      kaydet()

    # (A) konum taraması
    for ilk in ((0, 1, 3, 10, 100000) if arg.parca == "hepsi" else ()):
        t = time.time()
        y = y04.KararYonlendirici(katmanlar, v1, KATMANLAR, "iz", 1.0, ilk)
        try:
            g = olc_sayacli(model, tokenizer, onek, gel, et_gel, y)
            s = olc_sayacli(model, tokenizer, onek, sin, et_sin, y)
        finally:
            y.kapat()
        ad = f"konum: son istem konumu + ilk {ilk if ilk < 100000 else 'tüm'} token, a=1"
        cikti["konum"][str(ilk)] = {"gelistirme": g, "sinama": s}
        satir_yaz(ad, g, s, t)
        kaydet()

    # (B) rastgele yönler ve ters itme
    rng = np.random.default_rng(0)
    denemeler = []
    for i in range(3):
        r = rng.standard_normal(v1.shape).astype(np.float32)
        r /= np.linalg.norm(r, axis=-1, keepdims=True)
        denemeler.append((f"rastgele yön {i + 1}, itme b=0.5gap", r, 0.0, 0.5 * gap))
    for i in range(2):
        r = rng.standard_normal(v1.shape).astype(np.float32)
        r /= np.linalg.norm(r, axis=-1, keepdims=True)
        denemeler.append((f"rastgele yön {i + 4}, silme a=1.5", r, 1.5, 0.0))
    denemeler.append(("v1 ters itme b=-0.5gap (anlatmaya doğru)", v1, 0.0, -0.5 * gap))
    for ad, yn, a, b in denemeler:
        if ad in cikti["rastgele"]:
            continue
        t = time.time()
        d = y06.MLPDuzenleyici(katmanlar, yn, KATMANLAR, a, b)
        try:
            g = y06.olc(model, tokenizer, onek, gel, et_gel)
            s = y06.olc(model, tokenizer, onek, sin, et_sin)
        finally:
            d.kapat()
        cikti["rastgele"][ad] = {"gelistirme": g, "sinama": s, "kosinus_v1": [round(float(yn[l] @ v1[l]), 3) for l in KATMANLAR]}
        satir_yaz(ad, g, s, t)
        kaydet()
    print(f"bitti {time.time() - t0:.0f} sn")


if __name__ == "__main__":
    main()
