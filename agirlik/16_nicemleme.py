#!/usr/bin/env python3
"""Hakem isteği: düzenlemenin nicemleme adımına göre büyüklüğü ve yeniden nicemlemede ne kadarının kaldığı (üretim yok, yalnız ağırlık).
Katman 27-29 down_proj için: 4 bit nicemleme gürültüsünün RMS'i (adım/√12), silme (a=1, 1.5, 2) ve itme (10 kanal, b=0.5gap)
düzenlemelerinin RMS'i ve göreli Frobenius normu, 4 ve 8 bitte yeniden nicemlendikten sonra gerçekleşen değişimin amaçlanan
değişime izdüşümü (kalan pay) ve göreli hata.
    ../.venv/bin/python 16_nicemleme.py
Çıktı: cikti/16_nicemleme.json, cikti/16_nicemleme.md"""
import importlib
import json
import sys

import mlx.core as mx
import numpy as np

from ortak import CIKTI, model_yukle

y06 = importlib.import_module("06_yon_varyantlari")
KATMANLAR = [27, 28, 29]


def olcu(W, W_yeni, q, bits, u):
    """Amaçlanan ΔW ve bits bitte yeniden nicemlenince gerçekleşen ΔW."""
    delta = W_yeni - W
    w, sc, b = mx.quantize(W_yeni, group_size=q.group_size, bits=bits)
    W_q = mx.dequantize(w, sc, b, group_size=q.group_size, bits=bits).astype(mx.float32)
    w0, sc0, b0 = mx.quantize(W, group_size=q.group_size, bits=bits)
    W0_q = mx.dequantize(w0, sc0, b0, group_size=q.group_size, bits=bits).astype(mx.float32)
    gercek = W_q - W0_q
    nd = float(mx.sqrt(mx.sum(delta ** 2)))
    pay = float(mx.sum(gercek * delta)) / (nd ** 2)
    hata = float(mx.sqrt(mx.sum((gercek - delta) ** 2))) / nd
    # Davranışı belirleyen bileşen: u yönünde yazılan satır (uᵀ ΔW), yuvarlama gürültüsü bu toplamda büyük ölçüde sönümlenir
    gu, du = u @ gercek, u @ delta
    pay_u = float(mx.sum(gu * du)) / float(mx.sum(du * du))
    hata_u = float(mx.sqrt(mx.sum((gu - du) ** 2))) / float(mx.sqrt(mx.sum(du * du)))
    return {"kalan_pay": round(pay, 3), "goreli_hata": round(hata, 3), "yon_kalan_pay": round(pay_u, 3), "yon_goreli_hata": round(hata_u, 3),
            "temel_yuvarlama_rms": float(mx.sqrt(mx.mean((W0_q - W) ** 2)))}


def main():
    sys.stdout.reconfigure(line_buffering=True)
    yon = np.load(CIKTI / "06_yonler.npz")
    v1, gap = yon["v1"], yon["gap"]
    secim = json.loads((CIKTI / "09_kanallar.json").read_text(encoding="utf-8"))["v1 itme 10 kanal b=0.5gap"]
    model, _ = model_yukle()
    katmanlar = y06.KATMAN_YOLU(model)
    sonuc = {}
    satirlar = ["| Katman | Düzenleme | ΔW RMS / nicemleme gürültüsü RMS | göreli Frobenius | 4 bit kalan pay (matris / u yönü) | 4 bit göreli hata (matris / u yönü) | 8 bit kalan pay (matris / u yönü) | 8 bit göreli hata (matris / u yönü) |",
                "|---|---|---|---|---|---|---|---|"]
    for l in KATMANLAR:
        q = katmanlar[l].mlp.down_proj
        W = mx.dequantize(q.weight, q.scales, q.biases, group_size=q.group_size, bits=q.bits).astype(mx.float32)
        u = mx.array(v1[l].astype(np.float32))
        adim = q.scales.astype(mx.float32)
        gurultu_rms = float(mx.sqrt(mx.mean(adim ** 2))) / np.sqrt(12)  # düzgün nicemleyicide yuvarlama hatası RMS = adım/√12
        W_rms = float(mx.sqrt(mx.mean(W ** 2)))
        W_norm = float(mx.sqrt(mx.sum(W ** 2)))
        duzenlemeler = []
        for a in (1.0, 1.5, 2.0):
            duzenlemeler.append((f"silme a={a}", W - a * mx.outer(u, u @ W)))
        c = np.zeros(W.shape[1], dtype=np.float32)
        for j, k in zip(secim[str(l)]["kanallar"], secim[str(l)]["katsayilar"]):
            c[j] = k
        duzenlemeler.append(("itme 10 kanal b=0.5gap", W + mx.outer(u, mx.array(c))))
        sonuc[l] = {"nicemleme_gurultu_rms": gurultu_rms, "W_rms": W_rms, "W_rms_bolu_gurultu": W_rms / gurultu_rms, "duzenlemeler": {}}
        for ad, W_yeni in duzenlemeler:
            delta = W_yeni - W
            d_rms = float(mx.sqrt(mx.mean(delta ** 2)))
            if "itme" in ad:  # itme yalnız 10 sütunda: o sütunlardaki RMS de verilir
                sut = mx.take(delta, mx.array(np.array(secim[str(l)]["kanallar"], dtype=np.int32)), axis=1)
                sutun_rms = float(mx.sqrt(mx.mean(sut ** 2)))
            else:
                sutun_rms = None
            m4, m8 = olcu(W, W_yeni, q, 4, u), olcu(W, W_yeni, q, 8, u)
            kayit = {"delta_rms": d_rms, "delta_rms_bolu_gurultu": d_rms / gurultu_rms, "sutun_rms_bolu_gurultu": (sutun_rms / gurultu_rms) if sutun_rms else None,
                     "goreli_frobenius": float(mx.sqrt(mx.sum(delta ** 2))) / W_norm, "bit4": m4, "bit8": m8}
            sonuc[l]["duzenlemeler"][ad] = kayit
            oran = f"{d_rms / gurultu_rms:.2f}" + (f" (10 sütunda {sutun_rms / gurultu_rms:.1f})" if sutun_rms else "")
            satir = f"| {l} | {ad} | {oran} | {100 * kayit['goreli_frobenius']:.1f}% | {m4['kalan_pay']:.2f} / {m4['yon_kalan_pay']:.2f} | {m4['goreli_hata']:.2f} / {m4['yon_goreli_hata']:.2f} | {m8['kalan_pay']:.2f} / {m8['yon_kalan_pay']:.2f} | {m8['goreli_hata']:.2f} / {m8['yon_goreli_hata']:.2f} |"
            print(satir)
            satirlar.append(satir)
        print(f"  katman {l}: nicemleme gürültüsü RMS {gurultu_rms:.5f}, W RMS {W_rms:.4f} (oran {W_rms / gurultu_rms:.1f}), temel 4 bit yuvarlama RMS {m4['temel_yuvarlama_rms']:.6f}")
    (CIKTI / "16_nicemleme.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")
    (CIKTI / "16_nicemleme.md").write_text("\n".join(satirlar) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
