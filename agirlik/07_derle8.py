#!/usr/bin/env python3
"""Aşama 6, derleme (ikinci sürüm): 06'daki yön varyantlarından biri (v1, v2, vg) seçilen katmanların MLP çıkış
matrisinden silinir ve bu üç matris 4 bit yerine 8 bitte saklanır ki düzenleme yeniden sıkıştırmada kaybolmasın
(05'te a=1,0 düzenlemesinin kazancı 4 bitte yarıya indi). Diğer tüm ağırlıklar 4 bit kalır (+~40 MB).
İtme (bias) varyantı derlenemez: Qwen3.5 MLP'sinde bias yok.
    ../.venv/bin/python 07_derle8.py --yon v2 --a 1.5 --bits 8 --ad ema2 [--sil model_ema1]
Çıktı: cikti/model_<ad>/ ve ölçüm (05 ile aynı 76 istem + 06 sınama kümesi)."""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
from mlx_lm.utils import load_config, save_config, save_model, snapshot_download

from ortak import CIKTI, MODEL, model_yukle

sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module  # noqa: E402

derle05 = import_module("05_derle") if False else None  # (05'in olc işlevi aşağıda yeniden kullanılmaz; 06 ölçümü kullanılır)
y06 = import_module("06_yon_varyantlari")

KATMAN_YOLU = lambda model: model.language_model.model.layers  # noqa: E731


def duzenle(model, yon, secili, a, bits):
    for l in secili:
        q = KATMAN_YOLU(model)[l].mlp.down_proj
        u = mx.array(np.asarray(yon[l], dtype=np.float32))
        W = mx.dequantize(q.weight, q.scales, q.biases, group_size=q.group_size, bits=q.bits).astype(mx.float32)
        W_yeni = W - a * mx.outer(u, u @ W)
        w, s, b = mx.quantize(W_yeni, group_size=q.group_size, bits=bits)
        q.weight, q.scales, q.biases = w, s, b
        q.bits = bits
        mx.eval(q.weight, q.scales, q.biases)
        print(f"  katman {l} down_proj: göreli değişim {float(mx.sqrt(mx.sum((W_yeni - W) ** 2)) / mx.sqrt(mx.sum(W ** 2))):.4f}, {bits} bit")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--yon", default="v2", choices=["v1", "v2", "vg"])
    p.add_argument("--katman", default="27,28,29")
    p.add_argument("--a", type=float, default=1.5)
    p.add_argument("--bits", type=int, default=8)
    p.add_argument("--ad", default="ema2")
    p.add_argument("--sil", default="", help="yer açmak için önce silinecek model klasörü adı (örn. model_ema1)")
    arg = p.parse_args()
    secili = [int(k) for k in arg.katman.split(",")]
    yonler = np.load(CIKTI / "06_yonler.npz")[arg.yon]
    if arg.sil:
        shutil.rmtree(CIKTI / arg.sil, ignore_errors=True)
        print(f"silindi: {arg.sil}")
    model, tokenizer = model_yukle()
    print(f"düzenleniyor: yön {arg.yon}, katmanlar {secili}, a={arg.a}, {arg.bits} bit")
    duzenle(model, yonler, secili, arg.a, arg.bits)
    hedef = CIKTI / f"model_{arg.ad}"
    shutil.rmtree(hedef, ignore_errors=True)
    hedef.mkdir(parents=True)
    save_model(hedef, model)
    kaynak = Path(snapshot_download(MODEL, allow_patterns=["*.json", "*.jinja", "*.txt"]))
    cfg = load_config(kaynak)
    for l in secili:
        cfg["quantization"][f"language_model.model.layers.{l}.mlp.down_proj"] = {"group_size": cfg["quantization"]["group_size"], "bits": arg.bits}
    if "quantization_config" in cfg:
        cfg["quantization_config"] = cfg["quantization"]
    save_config(cfg, hedef / "config.json", keep_vision_config=True)
    for dosya in kaynak.iterdir():
        if dosya.suffix in (".json", ".jinja") and dosya.name not in ("config.json", "model.safetensors.index.json"):
            shutil.copyfile(dosya, hedef / dosya.name)
    print(f"kaydedildi: {hedef}")
    del model
    # Kaydedilmiş modeli yükleyip 06'nın iki kümesinde ölç
    model2, tokenizer2 = model_yukle(str(hedef))
    katmanlar = KATMAN_YOLU(model2)
    print("  yüklenen down_proj bitleri:", [KATMAN_YOLU(model2)[l].mlp.down_proj.bits for l in secili])
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    sonuc06 = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))["temel"]
    onek = y06.OnEk(model2, tokenizer2, y06.istem(tokenizer2, ozet["istemler"][0]), ozet["istemler"][0])
    gel_kume = [(s["grup"], s["soru"]) for s in sonuc06["gelistirme"]["ayrinti"]]
    gel_et = [s["temel"] for s in sonuc06["gelistirme"]["ayrinti"]]
    sin_kume = [(s["grup"], s["soru"]) for s in sonuc06["sinama"]["ayrinti"]]
    sin_et = [s["temel"] for s in sonuc06["sinama"]["ayrinti"]]
    t = time.time()
    g = y06.olc(model2, tokenizer2, onek, gel_kume, gel_et)
    s = y06.olc(model2, tokenizer2, onek, sin_kume, sin_et)
    satir = (f"derlenmiş {arg.ad} ({arg.yon}, a={arg.a}, {arg.bits} bit): geliştirme {g['arac_cagri']}/{g['arac_toplam']} "
             f"(düzelen {g['duzelen']}, bozulan {g['bozulan']}, gereksiz {g['gereksiz']}) | sınama {s['arac_cagri']}/{s['arac_toplam']} "
             f"(düzelen {s['duzelen']}, bozulan {s['bozulan']}, gereksiz {s['gereksiz']}) [{time.time() - t:.0f} sn]")
    print(satir)
    (CIKTI / f"07_{arg.ad}.json").write_text(json.dumps({"ayar": vars(arg), "gelistirme": g, "sinama": s}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
