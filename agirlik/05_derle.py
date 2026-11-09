#!/usr/bin/env python3
"""Aşama 4, ağırlığa derleme: seçilen katmanların MLP çıkış matrisinden (down_proj) "anlatma" yönü u boyunca yazdığı
bileşen silinir (Astra'nın tek ranklı düzenlemesi):  W_yeni = W - a · u (uᵀ W).
4 bitlik ağırlık açılır, düzenlenir, yeniden 4 bite sıkıştırılır; model yeni bir klasöre kaydedilir ve aynı istem
kümesiyle sınanır. Çıktı: cikti/model_<ad>/ (MLX modeli) ve cikti/05_<ad>.json (ölçüm).
    ../.venv/bin/python 05_derle.py --katman 27,28,29 --a 1.0 --ad ema1
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
from mlx_lm.utils import load_config, save_config, save_model

from ortak import ARAC_ISTEMEYEN, ARAC_ISTEYEN, CIKTI, MODEL, OnEk, arac_cagrilari, istem, model_yukle, uret

KATMAN_YOLU = lambda model: model.language_model.model.layers  # noqa: E731


def duzenle(model, yonler, secili, a):
    degisen = 0
    for l in secili:
        q = KATMAN_YOLU(model)[l].mlp.down_proj
        u = mx.array(yonler[l].astype(np.float32))
        W = mx.dequantize(q.weight, q.scales, q.biases, group_size=q.group_size, bits=q.bits).astype(mx.float32)  # (çıkış, giriş)
        W_yeni = W - a * mx.outer(u, u @ W)
        w, s, b = mx.quantize(W_yeni, group_size=q.group_size, bits=q.bits)
        q.weight, q.scales, q.biases = w, s, b
        mx.eval(q.weight, q.scales, q.biases)
        degisen += W.size
        fark = float(mx.sqrt(mx.sum((W_yeni - W) ** 2)) / mx.sqrt(mx.sum(W ** 2)))
        print(f"  katman {l} down_proj {tuple(W.shape)}: göreli değişim {fark:.4f}")
    return degisen


def olc(model, tokenizer, baslik):
    onek = OnEk(model, tokenizer, istem(tokenizer, ARAC_ISTEYEN[0]), ARAC_ISTEYEN[0])
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    kotu = {s for s, e in zip(ozet["istemler"], ozet["etiket"]) if e == "kotu"}
    sonuc = []
    t = time.time()
    for grup, soru in [("arac", s) for s in ozet["istemler"]] + [("duz", s) for s in ARAC_ISTEMEYEN]:
        cikti = uret(model, tokenizer, istem(tokenizer, soru), en_cok=120, onek=onek)
        sonuc.append({"grup": grup, "soru": soru, "arac": [c.get("name") for c in arac_cagrilari(cikti)], "cikti": cikti[:300]})
    a_ = [s for s in sonuc if s["grup"] == "arac"]
    d_ = [s for s in sonuc if s["grup"] == "duz"]
    print(f"{baslik}: araç isteyen {len(a_)} istemde {sum(1 for s in a_ if s['arac'])} araç çağrısı (temel 52); "
          f"araçsız {len(d_)} istemde {sum(1 for s in d_ if s['arac'])} gereksiz ({time.time() - t:.0f} sn)")
    print(f"  önceki kötü {len(kotu)} istemin {sum(1 for s in a_ if s['soru'] in kotu and s['arac'])}'i artık araç çağırıyor; "
          f"önceki iyi {sum(1 for s in a_ if s['soru'] not in kotu)} istemin {sum(1 for s in a_ if s['soru'] not in kotu and not s['arac'])}'i bozuldu")
    for s in d_:
        print(f"    {'ARAÇ!' if s['arac'] else 'metin'} | {s['soru'][:40]:<40} | {s['cikti'][:80].replace(chr(10), ' ')}")
    return sonuc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--katman", default="27,28,29")
    p.add_argument("--a", type=float, default=1.0)
    p.add_argument("--ad", default="ema1")
    p.add_argument("--olcme", action="store_true", help="kaydet ama sınama")
    p.add_argument("--sadece_olc", action="store_true", help="kayıtlı modeli yalnızca sına")
    arg = p.parse_args()
    secili = [int(k) for k in arg.katman.split(",")]
    yonler = np.load(CIKTI / "02_yonler.npz")["yonler"]
    hedef = CIKTI / f"model_{arg.ad}"
    if not arg.sadece_olc:
        model, tokenizer = model_yukle()
        print(f"düzenleniyor: katmanlar {secili}, a={arg.a}")
        n = duzenle(model, yonler, secili, arg.a)
        print(f"  {n:,} sayı yeniden yazıldı")
        if hedef.exists():
            shutil.rmtree(hedef)
        hedef.mkdir(parents=True)
        save_model(hedef, model)
        del model
    kaynak = Path(__import__("mlx_lm.utils", fromlist=["snapshot_download"]).snapshot_download(MODEL, allow_patterns=["*.json", "*.jinja", "*.txt"]))
    cfg = load_config(kaynak)
    save_config(cfg, hedef / "config.json", keep_vision_config=True)
    for dosya in kaynak.iterdir():
        if dosya.suffix in (".json", ".jinja") and dosya.name not in ("config.json", "model.safetensors.index.json"):
            shutil.copyfile(dosya, hedef / dosya.name)
    print(f"kaydedildi: {hedef}")
    if arg.olcme:
        return
    model2, tokenizer2 = model_yukle(str(hedef))
    sonuc = olc(model2, tokenizer2, f"derlenmiş model {arg.ad} (katman {secili}, a={arg.a})")
    (CIKTI / f"05_{arg.ad}.json").write_text(json.dumps({"katman": secili, "a": arg.a, "sonuc": sonuc}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
