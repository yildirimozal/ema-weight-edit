#!/usr/bin/env python3
"""Aşama 3b: yönlendirme yalnızca karar anında. 03'te yönü her konumda silmek araç çağrısının içeriğini bozdu
(iyi 52 → 49, kötü 15'in 7'si düzeldi). Burada iki değişiklik:
1. Yön, konu etkisini azaltmak için eş ailelerden çıkarılır: aynı tür istemlerde (hatırla, defter, slayt, dosya yaz)
   kötü - iyi farkları ortalanır ("aile" kipi); "hepsi" kipi 02'deki yön.
2. Yönlendirme yalnızca ilk K üretilen tokende uygulanır (ilk token = "<tool_call>" mi, metin mi kararı), sonrası serbest.
    ../.venv/bin/python 04_karar_noktasi.py --katman 27,28,29 --kip iz --a 1.0 --ilk 3 --yon aile
"""
import argparse
import json
import time

import mlx.core as mx
import numpy as np

from ortak import ARAC_ISTEMEYEN, ARAC_ISTEYEN, CIKTI, OnEk, arac_cagrilari, istem, katmanlari_coz, katmanlari_sar, model_yukle, uret

KATMAN_YOLU = lambda model: model.language_model.model.layers  # noqa: E731
AILELER = {
    "hafiza": ("unutma", "aklında", "hatırla", "not et", "not al", "hafızana"),
    "defter": ("defter",),
    "slayt": ("slayt", "sunum", "başa dön", "sonuna git", "geri git", "ilerlet"),
    "dosya_yaz": ("dosya yaz", "dosyası oluştur", "oluştur,", "sonuna", "satır ekle"),
    "pano": ("pano",),
}


def aile(soru):
    s = soru.lower()
    for ad, ipuclari in AILELER.items():
        if any(i in s for i in ipuclari):
            return ad
    return "diger"


def aile_yonu(H, etiket, istemler):
    """Aile içi kötü-iyi farklarının ortalaması (katman x gizli), birim."""
    farklar = []
    e = np.array(etiket)
    a = np.array([aile(s) for s in istemler])
    for ad in set(a):
        iyi, kotu = H[(a == ad) & (e == "iyi")], H[(a == ad) & (e == "kotu")]
        if len(iyi) and len(kotu):
            farklar.append((kotu.mean(0) - iyi.mean(0)) * np.sqrt(min(len(iyi), len(kotu))))
            print(f"  aile {ad}: iyi {len(iyi)}, kötü {len(kotu)}")
    u = np.mean(farklar, 0)
    return u / (np.linalg.norm(u, axis=-1, keepdims=True) + 1e-6)


class KararYonlendirici:
    """Seçili katmanlarda yönü bastırır. kip iz/kaydir: katman çıkışında (artık akım), yalnızca istemin son konumu ve
    ilk K üretilen tokende. kip mlp: yalnızca o katmanın MLP'sinin u boyunca yazdığı bileşen silinir, her konumda
    (ilk sınırı yok). mlp kipi doğrudan ağırlığa derlenebilir: W_down <- W_down - u (uᵀ W_down)."""

    def __init__(self, katmanlar, yonler, secili, kip, a, ilk):
        import mlx.nn as nn
        self.sayac = 0
        self.ilk = ilk
        self.kip = kip
        self.katmanlar = katmanlar
        self.secili = secili
        self.asil = {}
        self.asil_mlp = {}
        islevler = {}
        for l in secili:
            u = mx.array(yonler[l].astype(np.float32))
            if kip == "mlp":
                mlp = katmanlar[l].mlp

                class MLPSar(nn.Module):
                    def __init__(self, ic, _u):
                        super().__init__()
                        self.ic = ic
                        self._u = _u

                    def __call__(self, x):
                        o = self.ic(x).astype(mx.float32)
                        return (o - a * (o @ self._u)[..., None] * self._u).astype(x.dtype)
                self.asil_mlp[l] = mlp
                katmanlar[l].mlp = MLPSar(mlp, u)
                continue

            def f(out, _u=u):
                n = out.shape[1]
                if n > 1:  # istem işleniyor: yalnızca son konum (ilk tokenin kararı)
                    o = out.astype(mx.float32)
                    son = o[:, -1:, :]
                    son = son - a * (son @ _u)[..., None] * _u if kip == "iz" else son - a * _u
                    return mx.concatenate([o[:, :-1, :], son], axis=1).astype(out.dtype)
                if self.sayac < self.ilk:
                    o = out.astype(mx.float32)
                    return (o - a * (o @ _u)[..., None] * _u if kip == "iz" else o - a * _u).astype(out.dtype)
                return out
            islevler[l] = f
        if islevler:
            self.asil = katmanlari_sar(katmanlar, islevler)

    def adim(self):
        self.sayac += 1

    def sifirla(self):
        self.sayac = 0

    def kapat(self):
        katmanlari_coz(self.katmanlar, self.asil)
        for l, mlp in self.asil_mlp.items():
            self.katmanlar[l].mlp = mlp


def uret_sayacli(model, tokenizer, metin, onek, yonlendirici, en_cok=120):
    """uret ile aynı, ama her üretilen tokenden sonra sayaç ilerler (son katman sarmalayıcısı sayacı okur)."""
    from mlx_lm.generate import generate_step
    yonlendirici.sifirla()
    girdi = mx.array(onek.kalan(tokenizer, metin))
    cache = onek.kopya()
    parcalar = []
    for token, _ in generate_step(girdi, model, max_tokens=en_cok, prompt_cache=cache):
        t = int(token)
        yonlendirici.adim()
        if t in tokenizer.eos_token_ids:
            break
        parcalar.append(t)
    return tokenizer.decode(parcalar)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--katman", default="27,28,29")
    p.add_argument("--kip", default="iz", choices=["iz", "kaydir", "mlp"])
    p.add_argument("--a", type=float, default=1.0)
    p.add_argument("--ilk", type=int, default=3, help="yönlendirilen ilk üretilen token sayısı")
    p.add_argument("--yon", default="aile", choices=["aile", "hepsi"])
    arg = p.parse_args()
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    y = np.load(CIKTI / "02_yonler.npz")
    if arg.yon == "aile":
        H = np.load(CIKTI / "02_durumlar.npy")
        yonler = aile_yonu(H, ozet["etiket"], ozet["istemler"])
    else:
        yonler = y["yonler"]
    secili = [int(k) for k in arg.katman.split(",")]
    kotu = [s for s, e in zip(ozet["istemler"], ozet["etiket"]) if e == "kotu"]
    model, tokenizer = model_yukle()
    katmanlar = KATMAN_YOLU(model)
    onek = OnEk(model, tokenizer, istem(tokenizer, ARAC_ISTEYEN[0]), ARAC_ISTEYEN[0])
    etiketli = [("arac", s) for s in ozet["istemler"]] + [("duz", s) for s in ARAC_ISTEMEYEN]
    yon = KararYonlendirici(katmanlar, yonler, secili, arg.kip, arg.a, arg.ilk)
    t = time.time()
    sonuc = []
    try:
        for grup, soru in etiketli:
            cikti = uret_sayacli(model, tokenizer, istem(tokenizer, soru), onek, yon)
            sonuc.append({"grup": grup, "soru": soru, "arac": [c.get("name") for c in arac_cagrilari(cikti)], "cikti": cikti[:300]})
    finally:
        yon.kapat()
    a_ = [s for s in sonuc if s["grup"] == "arac"]
    d_ = [s for s in sonuc if s["grup"] == "duz"]
    kotu_simdi = [s for s in sonuc if s["soru"] in kotu]
    iyi_once = [s for s in a_ if s["soru"] not in kotu]
    print(f"karar noktası {arg.yon} {arg.kip} katman {secili} a={arg.a} ilk={arg.ilk}: araç isteyen {len(a_)} istemde "
          f"{sum(1 for s in a_ if s['arac'])} araç çağrısı (temel 52); araçsız {len(d_)} istemde {sum(1 for s in d_ if s['arac'])} gereksiz ({time.time() - t:.0f} sn)")
    print(f"  önceki kötü {len(kotu)} istemin {sum(1 for s in kotu_simdi if s['arac'])}'i artık araç çağırıyor; "
          f"önceki iyi {len(iyi_once)} istemin {sum(1 for s in iyi_once if not s['arac'])}'i bozuldu")
    for s in kotu_simdi:
        print(f"    {'ARAÇ' if s['arac'] else 'yok '} | {s['soru'][:45]:<45} | {s['cikti'][:70].replace(chr(10), ' ')}")
    for s in iyi_once:
        if not s["arac"]:
            print(f"    BOZULDU | {s['soru'][:45]:<45} | {s['cikti'][:70].replace(chr(10), ' ')}")
    for s in d_:
        if s["arac"]:
            print(f"    GEREKSİZ | {s['soru'][:45]:<45} | {s['cikti'][:70].replace(chr(10), ' ')}")
    (CIKTI / f"04_{arg.yon}_{arg.kip}_{'-'.join(map(str, secili))}_{arg.a}_ilk{arg.ilk}.json").write_text(
        json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
