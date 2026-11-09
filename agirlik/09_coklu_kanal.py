#!/usr/bin/env python3
"""Aşama 8: itmeyi ağırlığa derlenebilir biçimde kurmak.

08: tam itme b=0,5·gap iki kümede de gereksiz çağrı sıfırla neredeyse kusursuz (67/68, 39/40). Ama tek "sabit" kanal
üzerinden itme gürültülü (|ort|/std ≈ 3-4): sınamada 2/8 gereksiz. Burada itme birkaç yarı sabit kanala bölünür
(k kanal, her biri b/k katkı; bağımsız gürültü √k kadar azalır) ve istenirse silme ile birleştirilir. Emülasyon tam
olarak derlenecek ağırlığı taklit eder:  W' = (I - a·u·uᵀ)·W + u·cᵀ,  c yalnızca seçilen kanallarda sıfırdan farklı.
    ../.venv/bin/python 09_coklu_kanal.py
Çıktı: cikti/09_ozet.txt, cikti/09_sonuc.json (ayar başına ölçümler), cikti/09_kanallar.json (seçilen kanallar)."""
import importlib
import json
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from ortak import CIKTI, OnEk, istem, model_yukle

y06 = importlib.import_module("06_yon_varyantlari")
y08 = importlib.import_module("08_sabit_kanal")
KATMANLAR = [27, 28, 29]


class DownProjDuzenleyici(nn.Module):
    """W' x = W x - a (W x · u) u + Σ_i c_i x_{j_i} u   (derlenecek ağırlığın birebir emülasyonu)."""

    def __init__(self, ic, u, a, kanallar, katsayilar):
        super().__init__()
        self.ic, self.u, self.a = ic, u, a
        self.kanallar = mx.array(np.asarray(kanallar, dtype=np.int32))
        self.katsayilar = mx.array(np.asarray(katsayilar, dtype=np.float32))

    def __call__(self, x):
        o = self.ic(x).astype(mx.float32)
        if self.a:
            o = o - self.a * (o @ self.u)[..., None] * self.u
        xj = mx.take(x.astype(mx.float32), self.kanallar, axis=-1)          # (..., k)
        o = o + (xj @ self.katsayilar)[..., None] * self.u
        return o.astype(x.dtype)


def kanal_istatistikleri(model, tokenizer, onek, katmanlar, kume, adet=40):
    kayit = {l: y08.GirisKaydedici(katmanlar[l].mlp.down_proj) for l in KATMANLAR}
    for l in KATMANLAR:
        katmanlar[l].mlp.down_proj = kayit[l]
    try:
        tam = mx.array(tokenizer.encode(istem(tokenizer, kume[0][1]), add_special_tokens=False))
        model(tam[None])
        for _, soru in kume[:adet]:
            model(mx.array(onek.kalan(tokenizer, istem(tokenizer, soru)))[None], cache=onek.kopya())
    finally:
        for l in KATMANLAR:
            katmanlar[l].mlp.down_proj = kayit[l].ic
    ist = {}
    for l in KATMANLAR:
        n = kayit[l].n
        ort = np.array(kayit[l].toplam) / n
        std = np.sqrt(np.maximum(np.array(kayit[l].kare) / n - ort ** 2, 0))
        ist[l] = (ort, std)
    return ist


def kanal_sec(ort, std, k):
    """En sabit k kanal (|ort|/std) ve b=1 için katsayılar: her kanal b/k katkı verir -> c_i = -(1/k)/ort_i (yön -u itmesi)."""
    skor = np.abs(ort) / (std + 1e-6)
    secilen = np.argsort(skor)[::-1][:k]
    return secilen, np.array([-(1.0 / k) / ort[j] for j in secilen])


def main():
    sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()
    model, tokenizer = model_yukle()
    katmanlar = y06.KATMAN_YOLU(model)
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    sonuc06 = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))["temel"]
    yonler = np.load(CIKTI / "06_yonler.npz")
    v1, v2, gap = yonler["v1"], yonler["v2"], yonler["gap"]
    onek = OnEk(model, tokenizer, istem(tokenizer, ozet["istemler"][0]), ozet["istemler"][0])
    gel_kume = [(s["grup"], s["soru"]) for s in sonuc06["gelistirme"]["ayrinti"]]
    gel_et = [s["temel"] for s in sonuc06["gelistirme"]["ayrinti"]]
    sin_kume = [(s["grup"], s["soru"]) for s in sonuc06["sinama"]["ayrinti"]]
    sin_et = [s["temel"] for s in sonuc06["sinama"]["ayrinti"]]
    ist = kanal_istatistikleri(model, tokenizer, onek, katmanlar, gel_kume)
    print(f"kanal istatistikleri {time.time() - t0:.0f} sn")

    satirlar, hepsi, secimler = [], {}, {}

    def dene(ad, yon, a, b_kat, k):
        asil = {l: katmanlar[l].mlp.down_proj for l in KATMANLAR}
        secimler[ad] = {}
        for l in KATMANLAR:
            kanallar, kats = kanal_sec(*ist[l], k)
            secimler[ad][l] = {"kanallar": [int(j) for j in kanallar], "katsayilar": [float(c * b_kat * gap[l]) for c in kats]}
            katmanlar[l].mlp.down_proj = DownProjDuzenleyici(asil[l], mx.array(yon[l].astype(np.float32)), a, kanallar, kats * b_kat * gap[l])
        try:
            t = time.time()
            g = y06.olc(model, tokenizer, onek, gel_kume, gel_et)
            s = y06.olc(model, tokenizer, onek, sin_kume, sin_et)
        finally:
            for l in KATMANLAR:
                katmanlar[l].mlp.down_proj = asil[l]
        hepsi[ad] = {"gelistirme": g, "sinama": s}
        satir = (f"{ad:<40} geliştirme {g['arac_cagri']}/{g['arac_toplam']} (düzelen {g['duzelen']}, bozulan {g['bozulan']}, gereksiz {g['gereksiz']}) | "
                 f"sınama {s['arac_cagri']}/{s['arac_toplam']} (düzelen {s['duzelen']}, bozulan {s['bozulan']}, gereksiz {s['gereksiz']}) [{time.time() - t:.0f} sn]")
        print(satir)
        satirlar.append(satir)
        (CIKTI / "09_ozet.txt").write_text("\n".join(satirlar), encoding="utf-8")
        (CIKTI / "09_sonuc.json").write_text(json.dumps(hepsi, ensure_ascii=False, indent=1), encoding="utf-8")
        (CIKTI / "09_kanallar.json").write_text(json.dumps(secimler, ensure_ascii=False, indent=1), encoding="utf-8")

    dene("v1 itme 5 kanal b=0.5gap", v1, 0.0, 0.5, 5)
    dene("v1 itme 10 kanal b=0.5gap", v1, 0.0, 0.5, 10)
    dene("v1 itme 20 kanal b=0.5gap", v1, 0.0, 0.5, 20)
    dene("v2 silme a=1 + v2 itme 10 kanal b=0.5gap", v2, 1.0, 0.5, 10)
    dene("v1 itme 10 kanal b=0.4gap", v1, 0.0, 0.4, 10)


if __name__ == "__main__":
    main()
