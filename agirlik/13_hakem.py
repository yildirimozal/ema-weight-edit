#!/usr/bin/env python3
"""Aşama 11, hakem istekleri, temel ve itme modelleri için:
(1) Doğru araç analizi: 98 istemlik büyük sınamada araç adı ve alanları kaydedilir, istemin ailesine göre beklenen araçla
    karşılaştırılır. Soru: model daha çok mu çağırıyor, doğru aracı mı çağırıyor?
(2) İzin dağılımı: kaydedilen her araç çağrısı Ema'nın izin kararından (sunucu.karar) geçirilir: serbest / sor / yasak.
    Artan isteklilik, onay ya da yasak düzeyinde çağrı üretiyor mu?
(3) Yön duyarlılığı (yalnızca --yon_duyarliligi ile, temel modelde): 15 kötü örneğin 10'luk üç rastgele alt kümesinden yön
    çıkarılır, tam yönle kosinüs benzerliği yazılır ve 10 kanallı itme ile 40'lık sınama kümesinde ölçülür.
    ../.venv/bin/python 13_hakem.py --model <yol> --ad temel [--yon_duyarliligi]
Çıktı: cikti/13_<ad>.json, cikti/13_ozet.txt"""
import argparse
import importlib
import importlib.util
import json
import sys
import time

import mlx.core as mx
import numpy as np

from ortak import CIKTI, OnEk, arac_cagrilari, istem, model_yukle, uret

s11 = importlib.import_module("11_saglamlik")
y09 = importlib.import_module("09_coklu_kanal")
y06 = importlib.import_module("06_yon_varyantlari")
import izin as sunucu  # Ema'nın izin kararının dondurulmuş kopyası (izin.py)

AILE = [  # (beklenen araçlar, ipuçları); ilk eşleşen aile geçerli
    (("hafiza",), ("hatırla", "unutma", "aklında", "not al", "not et", "hafıza", "hafızan")),
    (("defter",), ("defter",)),
    (("pano", "quiz"), ("sınav", "quiz")),
    (("pano",), ("pano",)),
    (("sunum", "Glob", "Bash"), ("slayt", "sunum")),
    (("zaman",), ("zaman aracı",)),
    (("telefon",), ("telefon",)),
    (("dogrula",), ("doğrula", "dogrula")),
    (("Write", "Edit", "Bash", "Glob"), ("oluştur", "yaz,", "ekle:", "yazsın", "satır ekle", "yap.")),
    (("Glob", "Bash", "Read", "Grep"), ("kaç", "var mı", "oku", "ne yazıyor", "listele", "hangisi", "say.", "bul", "dosya", "değişen", "aç.")),
]


def beklenen(soru):
    s = soru.lower()
    for araclar, ipuclari in AILE:
        if any(i in s for i in ipuclari):
            return araclar
    return ()


YERLESIK = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch")


def izin(ad, girdi):
    """Ema'nın izin kararı: yerleşik araçlar aynı adla, Ema araçları mcp__sahne__ önekiyle."""
    try:
        return sunucu.karar({"tool_name": ad if ad in YERLESIK else f"mcp__sahne__{ad}", "input": girdi if isinstance(girdi, dict) else {}})
    except Exception:
        return "hata"


def dogru_arac(model, tokenizer, onek, sistem):
    sonuc = []
    for soru in s11.BUYUK_ARAC:
        sunucu.SON_SORU["metin"] = soru
        c = uret(model, tokenizer, istem(tokenizer, soru, sistem=sistem), en_cok=160, onek=onek)
        cagrilar = arac_cagrilari(c)
        adlar = [x.get("name") for x in cagrilar]
        bek = beklenen(soru)
        dogru = any(a in bek for a in adlar) if bek else bool(adlar)
        kararlar = [izin(x.get("name"), x.get("arguments") or {}) for x in cagrilar if x.get("name") and x.get("name") != "_ham"]
        sonuc.append({"soru": soru, "araclar": adlar, "argumanlar": [x.get("arguments") for x in cagrilar][:2], "beklenen": list(bek),
                      "cagri_var": bool(adlar), "dogru_arac": dogru, "kararlar": kararlar})
    n = len(sonuc)
    return {"n": n, "cagri": sum(s["cagri_var"] for s in sonuc), "dogru": sum(s["dogru_arac"] for s in sonuc),
            "yanlis_arac": sum(1 for s in sonuc if s["cagri_var"] and not s["dogru_arac"]),
            "izin": {k: sum(x.count(k) for x in (s["kararlar"] for s in sonuc)) for k in ("serbest", "sor", "yasak")}, "ayrinti": sonuc}


def yon_duyarliligi(model, tokenizer, onek, sistem):
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    H = np.load(CIKTI / "02_durumlar.npy")
    e = np.array(ozet["etiket"])
    iyi, kotu = H[e == "iyi"], H[e == "kotu"]
    tam = np.load(CIKTI / "06_yonler.npz")["v1"]
    gap_tam = np.load(CIKTI / "06_yonler.npz")["gap"]
    sonuc06 = json.loads((CIKTI / "06_sonuc.json").read_text(encoding="utf-8"))["temel"]
    sin_kume = [(s["grup"], s["soru"]) for s in sonuc06["sinama"]["ayrinti"]]
    sin_et = [s["temel"] for s in sonuc06["sinama"]["ayrinti"]]
    katmanlar = y06.KATMAN_YOLU(model)
    ist = y09.kanal_istatistikleri(model, tokenizer, onek, katmanlar, [("arac", s) for s in ozet["istemler"]])
    rng = np.random.default_rng(7)
    # Önce 200 yeniden örneklemeyle kosinüs dağılımı (hesap yalnız)
    kos = {l: [] for l in y09.KATMANLAR}
    for _ in range(200):
        sec = rng.choice(len(kotu), size=10, replace=False)
        for l in y09.KATMANLAR:
            u = kotu[sec, l].mean(0) - iyi[:, l].mean(0)
            u /= np.linalg.norm(u) + 1e-6
            kos[l].append(float(u @ tam[l]))
    kosinus = {l: (round(float(np.mean(v)), 3), round(float(np.min(v)), 3)) for l, v in kos.items()}
    print("  10'luk alt kümelerden yönlerin tam yönle kosinüsü (ortalama, en düşük):", kosinus)
    denemeler = []
    for d in range(3):
        sec = rng.choice(len(kotu), size=10, replace=False)
        yon = np.zeros_like(tam)
        gap = np.zeros(len(tam))
        for l in range(len(tam)):
            u = kotu[sec, l].mean(0) - iyi[:, l].mean(0)
            yon[l] = u / (np.linalg.norm(u) + 1e-6)
            gap[l] = float(kotu[sec, l].mean(0) @ yon[l] - iyi[:, l].mean(0) @ yon[l])
        asil = {l: katmanlar[l].mlp.down_proj for l in y09.KATMANLAR}
        for l in y09.KATMANLAR:
            kanallar, kats = y09.kanal_sec(*ist[l], 10)
            katmanlar[l].mlp.down_proj = y09.DownProjDuzenleyici(asil[l], mx.array(yon[l].astype(np.float32)), 0.0, kanallar, kats * 0.5 * gap[l])
        try:
            s = y06.olc(model, tokenizer, onek, sin_kume, sin_et)
        finally:
            for l in y09.KATMANLAR:
                katmanlar[l].mlp.down_proj = asil[l]
        denemeler.append({"alt_kume": [int(i) for i in sec], "kosinus_27_29": [round(float(yon[l] @ tam[l]), 3) for l in y09.KATMANLAR],
                          "sinama_cagri": s["arac_cagri"], "gereksiz": s["gereksiz"], "duzelen": s["duzelen"], "bozulan": s["bozulan"]})
        print(f"  alt küme {d + 1}: kosinüs {denemeler[-1]['kosinus_27_29']}, sınama {s['arac_cagri']}/40, gereksiz {s['gereksiz']}/8")
    return {"kosinus_200": kosinus, "denemeler": denemeler}


def main():
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--ad", required=True)
    p.add_argument("--yon_duyarliligi", action="store_true")
    arg = p.parse_args()
    t0 = time.time()
    model, tokenizer = model_yukle(arg.model)
    sistem = s11.talimat()
    onek = OnEk(model, tokenizer, istem(tokenizer, s11.BUYUK_ARAC[0], sistem=sistem), s11.BUYUK_ARAC[0])
    print(f"{arg.ad}: hazır {time.time() - t0:.0f} sn")
    da = dogru_arac(model, tokenizer, onek, sistem)
    satir = (f"{arg.ad:<12} 98 istem: çağrı {da['cagri']}, doğru araç {da['dogru']}, yanlış araç {da['yanlis_arac']}, "
             f"izin dağılımı serbest {da['izin']['serbest']} / sor {da['izin']['sor']} / yasak {da['izin']['yasak']} ({time.time() - t0:.0f} sn)")
    print(satir)
    cikti = {"ayar": vars(arg), "dogru_arac": da}
    if arg.yon_duyarliligi:
        cikti["yon_duyarliligi"] = yon_duyarliligi(model, tokenizer, onek, sistem)
    (CIKTI / f"13_{arg.ad}.json").write_text(json.dumps(cikti, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(CIKTI / "13_ozet.txt", "a", encoding="utf-8") as f:
        f.write(satir + "\n")


if __name__ == "__main__":
    main()
