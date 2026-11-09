#!/usr/bin/env python3
"""Ayrı koşumların (sonuc_*.json) sonuçlarını tek raporda birleştirir: .venv/bin/python kiyaslama/birlestir.py
Aynı motorun son tam koşumu alınır; sonraki kısmi koşumlar (--gorev ile yeniden koşulan görevler) o görevlerin üstüne yazılır."""
import glob
import json
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import kiyasla  # noqa: E402

hepsi = {}
for dosya in sorted(glob.glob(str(KOK / "kiyaslama" / "sonuc_*.json"))):
    for motor, sonuclar in json.load(open(dosya, encoding="utf-8")).items():
        if len(sonuclar) == len(kiyasla.GOREVLER):
            hepsi[motor] = sonuclar
        elif motor in hepsi:
            for s in sonuclar:
                hepsi[motor] = [s if e["gorev"] == s["gorev"] else e for e in hepsi[motor]]
# uydurmama görevinin denetimi ilk koşumdan sonra düzeltildi ("özetleyeyim mi" sorusu ceza almasın): metinden yeniden
kontrol = next(g["kontrol"] for g in kiyasla.GOREVLER if g["ad"] == "uydurmama")
for sonuclar in hepsi.values():
    for s in sonuclar:
        if s["gorev"] == "uydurmama":
            s["basarili"] = bool(kontrol(s["cevap"], [], Path("."))) and not s["hata"]
sira = ["claude:sonnet", "yerel:qwen3.5:4b", "yerel:~/sahne_asistani/agirlik/cikti/model_ema1", "yerel:~/sahne_asistani/agirlik/cikti/model_ema2", "yerel:qwen3.5:9b", "yerel:qwen2.5:7b"]
hepsi = {m: hepsi[m] for m in sira if m in hepsi} | {m: v for m, v in hepsi.items() if m not in sira}
KISA = {"yerel:~/sahne_asistani/agirlik/cikti/model_ema1": "yerel:qwen3.5-4b-silme (MLX)",
        "yerel:~/sahne_asistani/agirlik/cikti/model_ema2": "yerel:qwen3.5-4b-itme (MLX)"}
hepsi = {KISA.get(m, m): v for m, v in hepsi.items()}
yol = KOK / "kiyaslama" / "rapor.md"
kiyasla.rapor_yaz(hepsi, yol)
for m, l in hepsi.items():
    print(m, kiyasla.ozetle(l))
print("Rapor:", yol)
