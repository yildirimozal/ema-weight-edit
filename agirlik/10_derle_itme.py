#!/usr/bin/env python3
"""Aşama 9, itmeyi ağırlığa derleme: 09'da seçilen k yarı sabit kanal üzerinden sabit itme, istenirse silme ile.
    W' = (I - a·u·uᵀ)·W + u·cᵀ      (c: 09_kanallar.json'daki kanallar ve katsayılar; katsayılar b·gap içerir)
Düzenlenen üç down_proj matrisi 8 bitte saklanır (küçük düzenleme 4 bit yuvarlamasında kaybolmasın).
    ../.venv/bin/python 10_derle_itme.py --ayar "v1 itme 5 kanal b=0.5gap" --ad ema2 [--sil model_ema1]
Çıktı: cikti/model_<ad>/, cikti/10_<ad>.json (geliştirme + sınama ölçümü)."""
import argparse
import importlib
import json
import shutil
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
from mlx_lm.utils import load_config, save_config, save_model, snapshot_download

from ortak import CIKTI, MODEL, model_yukle

y06 = importlib.import_module("06_yon_varyantlari")
KATMANLAR = [27, 28, 29]


def main():
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--ayar", default="v1 itme 5 kanal b=0.5gap", help="09_kanallar.json'daki ayar adı")
    p.add_argument("--yon", default="v1", choices=["v1", "v2"])
    p.add_argument("--a", type=float, default=0.0, help="silme şiddeti (ayarda silme varsa 1.0)")
    p.add_argument("--bits", type=int, default=8)
    p.add_argument("--ad", default="ema2")
    p.add_argument("--sil", default="")
    arg = p.parse_args()
    secim = json.loads((CIKTI / "09_kanallar.json").read_text(encoding="utf-8"))[arg.ayar]
    yon = np.load(CIKTI / "06_yonler.npz")[arg.yon]
    if arg.sil:
        shutil.rmtree(CIKTI / arg.sil, ignore_errors=True)
        print("silindi:", arg.sil)
    model, tokenizer = model_yukle()
    katmanlar = y06.KATMAN_YOLU(model)
    for l in KATMANLAR:
        q = katmanlar[l].mlp.down_proj
        u = mx.array(yon[l].astype(np.float32))
        W = mx.dequantize(q.weight, q.scales, q.biases, group_size=q.group_size, bits=q.bits).astype(mx.float32)
        W_yeni = W - arg.a * mx.outer(u, u @ W) if arg.a else W
        c = np.zeros(W.shape[1], dtype=np.float32)
        s = secim[str(l)]
        for j, k in zip(s["kanallar"], s["katsayilar"]):
            c[j] = k
        W_yeni = W_yeni + mx.outer(u, mx.array(c))
        w, sc, b = mx.quantize(W_yeni, group_size=q.group_size, bits=arg.bits)
        q.weight, q.scales, q.biases, q.bits = w, sc, b, arg.bits
        mx.eval(q.weight, q.scales, q.biases)
        print(f"  katman {l}: kanallar {s['kanallar']}, göreli değişim {float(mx.sqrt(mx.sum((W_yeni - W) ** 2)) / mx.sqrt(mx.sum(W ** 2))):.4f}, {arg.bits} bit")
    hedef = CIKTI / f"model_{arg.ad}"
    shutil.rmtree(hedef, ignore_errors=True)
    hedef.mkdir(parents=True)
    save_model(hedef, model)
    kaynak = Path(snapshot_download(MODEL, allow_patterns=["*.json", "*.jinja", "*.txt"]))
    cfg = load_config(kaynak)
    for l in KATMANLAR:
        cfg["quantization"][f"language_model.model.layers.{l}.mlp.down_proj"] = {"group_size": cfg["quantization"]["group_size"], "bits": arg.bits}
    if "quantization_config" in cfg:
        cfg["quantization_config"] = cfg["quantization"]
    save_config(cfg, hedef / "config.json", keep_vision_config=True)
    for dosya in kaynak.iterdir():
        if dosya.suffix in (".json", ".jinja") and dosya.name not in ("config.json", "model.safetensors.index.json"):
            shutil.copyfile(dosya, hedef / dosya.name)
    print("kaydedildi:", hedef)
    del model
    model2, tokenizer2 = model_yukle(str(hedef))
    print("  yüklenen bitler:", [y06.KATMAN_YOLU(model2)[l].mlp.down_proj.bits for l in KATMANLAR])
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    temel = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))["temel"]
    onek = y06.OnEk(model2, tokenizer2, y06.istem(tokenizer2, ozet["istemler"][0]), ozet["istemler"][0])
    t = time.time()
    g = y06.olc(model2, tokenizer2, onek, [(s["grup"], s["soru"]) for s in temel["gelistirme"]["ayrinti"]], [s["temel"] for s in temel["gelistirme"]["ayrinti"]])
    s_ = y06.olc(model2, tokenizer2, onek, [(s["grup"], s["soru"]) for s in temel["sinama"]["ayrinti"]], [s["temel"] for s in temel["sinama"]["ayrinti"]])
    satir = (f"derlenmiş {arg.ad} ({arg.ayar}, a={arg.a}, {arg.bits} bit): geliştirme {g['arac_cagri']}/{g['arac_toplam']} "
             f"(düzelen {g['duzelen']}, bozulan {g['bozulan']}, gereksiz {g['gereksiz']}) | sınama {s_['arac_cagri']}/{s_['arac_toplam']} "
             f"(düzelen {s_['duzelen']}, bozulan {s_['bozulan']}, gereksiz {s_['gereksiz']}) [{time.time() - t:.0f} sn]")
    print(satir)
    (CIKTI / f"10_{arg.ad}.json").write_text(json.dumps({"ayar": vars(arg), "gelistirme": g, "sinama": s_}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
