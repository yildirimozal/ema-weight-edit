#!/usr/bin/env python3
"""Aşama 7: itmeyi ağırlığa derlemenin yolu ve kalibrasyonu.

06'da "itme" (MLP çıkışına her konumda -b·u eklemek) silmeden çok daha güçlü çıktı (geliştirme 68/68, sınama 40/40),
ama Qwen3.5 MLP'sinde bias yok. Çare: down_proj girişinde (act(gate)·up, 9216 kanal) her tokende neredeyse sabit bir
kanal j bulmak; o zaman W[:, j] -= (b / ort_j)·u, çıkışa yaklaşık -b·u ekler ve bu gerçek bir ağırlık düzenlemesidir.
1. Katman 27-29'da down_proj girişinin kanal başına ortalaması ve yayılımı ölçülür (geliştirme istemleri, tüm konumlar).
2. En sabit kanal seçilir; ağırlık sütunu düzenlenmiş gibi çalışma anında emüle edilir (W x + (-b/ort_j) u x_j).
3. b için kalibrasyon: 0,5·gap, 0,75·gap, 1,0·gap; tam itme ile kanal yoluyla itme yan yana, iki kümede.
Çıktı: cikti/08_kanal.json, cikti/08_ozet.txt"""
import json
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from ortak import CIKTI, OnEk, istem, model_yukle
import importlib
y06 = importlib.import_module("06_yon_varyantlari")

KATMANLAR = [27, 28, 29]


class GirisKaydedici(nn.Module):
    """down_proj'un girişini (toplam, kareler toplamı, konum sayısı) biriktirir."""

    def __init__(self, ic):
        super().__init__()
        self.ic = ic
        self.toplam = None
        self.kare = None
        self.n = 0

    def __call__(self, x):
        x32 = x.astype(mx.float32).reshape(-1, x.shape[-1])
        t, k = mx.sum(x32, axis=0), mx.sum(x32 * x32, axis=0)
        mx.eval(t, k)
        self.toplam = t if self.toplam is None else self.toplam + t
        self.kare = k if self.kare is None else self.kare + k
        self.n += x32.shape[0]
        return self.ic(x)


class KanalItici(nn.Module):
    """down_proj yerine: W x + katsayi · u · x_j  (W[:, j] sütununa katsayi·u eklenmiş gibi)."""

    def __init__(self, ic, u, j, katsayi):
        super().__init__()
        self.ic, self.u, self.j, self.katsayi = ic, u, j, katsayi

    def __call__(self, x):
        o = self.ic(x).astype(mx.float32)
        xj = x[..., self.j:self.j + 1].astype(mx.float32)
        return (o + self.katsayi * xj * self.u).astype(x.dtype)


class TamItici(nn.Module):
    def __init__(self, ic, u, b):
        super().__init__()
        self.ic, self.u, self.b = ic, u, b

    def __call__(self, x):
        return (self.ic(x).astype(mx.float32) - self.b * self.u).astype(x.dtype)


def main():
    sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()
    model, tokenizer = model_yukle()
    katmanlar = y06.KATMAN_YOLU(model)
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    sonuc06 = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))["temel"]
    yonler = np.load(CIKTI / "06_yonler.npz")
    v1, gap = yonler["v1"], yonler["gap"]
    onek = OnEk(model, tokenizer, istem(tokenizer, ozet["istemler"][0]), ozet["istemler"][0])
    gel_kume = [(s["grup"], s["soru"]) for s in sonuc06["gelistirme"]["ayrinti"]]
    gel_et = [s["temel"] for s in sonuc06["gelistirme"]["ayrinti"]]
    sin_kume = [(s["grup"], s["soru"]) for s in sonuc06["sinama"]["ayrinti"]]
    sin_et = [s["temel"] for s in sonuc06["sinama"]["ayrinti"]]

    # 1. Kanal istatistikleri: istemleri (ön ek hariç kısım + ön ek bir kez) katmanlardan geçir
    kayit = {}
    for l in KATMANLAR:
        kayit[l] = GirisKaydedici(katmanlar[l].mlp.down_proj)
        katmanlar[l].mlp.down_proj = kayit[l]
    try:
        # Ön ekin kendisi de dahil (talimat tokenleri): tam istem bir kez önbelleksiz işlenir
        tam = mx.array(tokenizer.encode(istem(tokenizer, ozet["istemler"][0]), add_special_tokens=False))
        model(tam[None])
        for _, soru in gel_kume[:40]:
            tokens = mx.array(onek.kalan(tokenizer, istem(tokenizer, soru)))
            model(tokens[None], cache=onek.kopya())
    finally:
        for l in KATMANLAR:
            katmanlar[l].mlp.down_proj = kayit[l].ic
    kanal = {}
    for l in KATMANLAR:
        n = kayit[l].n
        ort = np.array(kayit[l].toplam) / n
        std = np.sqrt(np.maximum(np.array(kayit[l].kare) / n - ort ** 2, 0))
        skor = np.abs(ort) / (std + 1e-6)   # sabitlik: |ortalama| / yayılım
        sira = np.argsort(skor)[::-1]
        kanal[l] = {"j": int(sira[0]), "ort": float(ort[sira[0]]), "std": float(std[sira[0]]), "skor": float(skor[sira[0]]),
                    "ilk5": [(int(j), round(float(ort[j]), 4), round(float(std[j]), 4), round(float(skor[j]), 2)) for j in sira[:5]]}
        print(f"katman {l}: {n} konum; en sabit kanal {kanal[l]['j']} ort {kanal[l]['ort']:.4f} std {kanal[l]['std']:.4f} "
              f"(|ort|/std {kanal[l]['skor']:.1f}); ilk 5: {kanal[l]['ilk5']}")
    (CIKTI / "08_kanal.json").write_text(json.dumps(kanal, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"istatistik {time.time() - t0:.0f} sn")

    # 2-3. Kalibrasyon ve emülasyon
    satirlar = []

    def dene(ad, kur):
        asil = {l: katmanlar[l].mlp.down_proj for l in KATMANLAR}
        for l in KATMANLAR:
            katmanlar[l].mlp.down_proj = kur(l, asil[l])
        try:
            t = time.time()
            g = y06.olc(model, tokenizer, onek, gel_kume, gel_et)
            s = y06.olc(model, tokenizer, onek, sin_kume, sin_et)
        finally:
            for l in KATMANLAR:
                katmanlar[l].mlp.down_proj = asil[l]
        satir = (f"{ad:<34} geliştirme {g['arac_cagri']}/{g['arac_toplam']} (düzelen {g['duzelen']}, bozulan {g['bozulan']}, gereksiz {g['gereksiz']}) | "
                 f"sınama {s['arac_cagri']}/{s['arac_toplam']} (düzelen {s['duzelen']}, bozulan {s['bozulan']}, gereksiz {s['gereksiz']}) [{time.time() - t:.0f} sn]")
        print(satir)
        satirlar.append(satir)
        (CIKTI / "08_ozet.txt").write_text("\n".join(satirlar), encoding="utf-8")
        return g, s

    for k in (0.5, 0.75):
        dene(f"tam itme b={k}gap", lambda l, ic, k=k: TamItici(ic, mx.array(v1[l].astype(np.float32)), k * float(gap[l])))
    for k in (0.5, 0.75, 1.0):
        dene(f"kanal itme b={k}gap", lambda l, ic, k=k: KanalItici(ic, mx.array(v1[l].astype(np.float32)), kanal[l]["j"],
                                                                  -k * float(gap[l]) / kanal[l]["ort"]))


if __name__ == "__main__":
    main()
