#!/usr/bin/env python3
"""Aşama 5: düzenleme algoritmasının varyantları, dürüst ölçümle.

Önceki yöntem (02-05): yön = ort(kötü) - ort(iyi), katman 27-29 MLP çıkışından silinir. Zayıflıkları: yön konu bilgisi
taşıyor (iyilerin bir kısmı bozuluyor), yalnızca silme deneniyor, ölçüm yönün çıkarıldığı istemlerde yapılıyor.
Burada:
  - Yön varyantları: V1 ham ortalama farkı; V2 iyi kümenin ana bileşenlerinden arındırılmış fark; VG gradyan yönü
    (ilk tokenin <tool_call> olma log-olasılığının katman çıkışına göre türevi, kötü istemler üzerinde ortalama).
  - Uygulama varyantları (hepsi MLP çıkışında, her konumda, yani ağırlığa derlenebilir): silme (o - a (o·u) u),
    itme (o - b u, yani sabit yanlılık; ağırlıkta bias terimi), ikisi birlikte.
  - Ölçüm: yönün çıkarıldığı 68 istem (geliştirme) ve hiç görülmemiş 40 araç + 8 düz istem (sınama).
Çıktı: cikti/06_sonuc.json, cikti/06_ozet.txt
"""
import json
import sys
import time

import mlx.core as mx
import numpy as np

from ortak import ARAC_ISTEMEYEN, CIKTI, OnEk, arac_cagrilari, istem, katmanlari_coz, katmanlari_sar, model_yukle, uret

KATMAN_YOLU = lambda model: model.language_model.model.layers  # noqa: E731
ARAC_TOKEN = 248058  # "<tool_call>"
KATMANLAR = [27, 28, 29]

SINAMA_ARAC = [
    "Hatırla: dişçi randevum çarşamba dörtte.", "Unutma: Mehmet'e makaleyi göndereceğim.", "Aklında olsun: kapı şifresi değil, posta kutusu numarası yedi.",
    "Not al: bölüm başkanı pazartesi izinli.", "Aklında bulunsun: projeksiyon kablosu laboratuvarda.", "Şunu hatırla: tez jürisi on altısında.",
    "İkinci slayta geç.", "Sunumun başına dön.", "Bir önceki slayt.", "Dördüncü slayta git.", "Sunumu kapatır mısın.",
    "Panoda şunları göster: DNA, RNA, protein.", "Panoda üç maddelik özet göster: giriş, yöntem, bulgular.", "Panoyu kapat lütfen.",
    "Hücre bölünmesi konusunda dört soruluk mini sınav aç.", "Öğrencilere iki soruluk kısa bir quiz yap.",
    "Deftere yaz: altıncı hafta, indeksleme anlatıldı.", "Deftere kaydet: öğrenciler alt sorgularda zorlandı.", "Defterde indeksleme geçen kaydı bul.",
    "Hafta altı sunumunu aç.", "İstatistik dersinin hafta iki sunumunu göster.", "Masaüstündeki rapor taslağını aç.",
    "Belgeler klasöründe kaç tane docx var?", "İndirilenler'de pdf dosyası var mı?", "Deneme klasöründeki md dosyalarını say.",
    "notlar.txt dosyasının ikinci satırında ne yazıyor?", "Masaüstünde içinde bütçe geçen dosyayı bul.", "Deneme klasöründe papatya kelimesi geçiyor mu?",
    "Çalışma klasörüne gorevler.txt yaz, içine üç görev yaz.", "Masaüstüne not.txt oluştur, içine merhaba yaz.", "ozet.txt dosyasına yeni bir satır ekle: ders iptal.",
    "Neleri hatırlıyorsun, say.", "Hafızandaki ilk notu sil.", "Hafızada kahve ile ilgili not var mı?",
    "Bir saat sonrası saat kaç olur, zaman aracıyla bak.", "Yarın saat dokuzun tam zamanını zaman aracıyla ver.",
    "Çalışma klasöründe liste.csv adında dosya oluştur, içine ad,soyad yaz.", "Deneme klasöründeki dosyaların boyutlarını söyle.",
    "Masaüstündeki en yeni pdf hangisi?", "Dünkü ders özetini defterde ara.",
]
SINAMA_DUZ = [
    "Kaç kıta var?", "Suyun kaynama noktası kaç derece?", "Bugün günlerden ne?", "İki kere on iki kaç eder?",
    "Fotosentezde oksijen nereden çıkar, tek cümle.", "Nasılsın bugün?", "Ankara'nın plaka kodu kaç?", "Bana kısa bir tekerleme söyle.",
]


def etiketle(model, tokenizer, onek, istemler):
    """Temel davranış: iyi (araç çağırdı), kotu (çağırmadı, yaptım dedi), soru (karşı soru sordu)."""
    etiket, cikti_ = [], []
    for soru in istemler:
        c = uret(model, tokenizer, istem(tokenizer, soru), en_cok=120, onek=onek)
        iyi = bool(arac_cagrilari(c))
        etiket.append("iyi" if iyi else "soru" if c.strip().endswith("?") else "kotu")
        cikti_.append(c[:160])
    return etiket, cikti_


def pca_arindir(u, iyi_durumlar, k=5):
    """İyi kümenin ilk k ana bileşenini yönden çıkarır (konu bilgisi büyük ölçüde oradadır)."""
    X = iyi_durumlar - iyi_durumlar.mean(0)
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    for v in Vt[:k]:
        u = u - (u @ v) * v
    return u / (np.linalg.norm(u) + 1e-6)


def gradyan_yonu(model, tokenizer, onek, katmanlar, l, istemler):
    """Katman l çıkışının son konumuna eklenen bir sapmaya göre log p(<tool_call>) türevi, istemler üzerinde ortalama."""
    tutucu = {"delta": None}

    def ekle(out):
        if tutucu["delta"] is None:
            return out
        son = out[:, -1:, :].astype(mx.float32) + tutucu["delta"]
        return mx.concatenate([out[:, :-1, :], son.astype(out.dtype)], axis=1)
    asil = katmanlari_sar(katmanlar, {l: ekle})
    toplam = np.zeros(2560, dtype=np.float32)
    try:
        for soru in istemler:
            tokens = mx.array(onek.kalan(tokenizer, istem(tokenizer, soru)))

            def logp(delta):
                tutucu["delta"] = delta
                cache = onek.kopya()
                lg = model(tokens[None], cache=cache)[0, -1].astype(mx.float32)
                return lg[ARAC_TOKEN] - mx.logsumexp(lg)
            g = mx.grad(logp)(mx.zeros((2560,), dtype=mx.float32))
            mx.eval(g)
            tutucu["delta"] = None
            toplam += np.array(g)
    finally:
        tutucu["delta"] = None
        katmanlari_coz(katmanlar, asil)
    return toplam / (np.linalg.norm(toplam) + 1e-6)


class MLPDuzenleyici:
    """Seçili katmanların MLP çıkışında: o - a (o·u) u - b u (her konumda; ağırlığa derlenebilir)."""

    def __init__(self, katmanlar, yonler, secili, a, b):
        import mlx.nn as nn
        self.katmanlar, self.asil = katmanlar, {}
        for l in secili:
            u = mx.array(np.asarray(yonler[l], dtype=np.float32))
            b_l = float(b[l]) if hasattr(b, "__getitem__") else float(b)

            class Sar(nn.Module):
                def __init__(self, ic, _u, _b):
                    super().__init__()
                    self.ic, self._u, self._b = ic, _u, _b

                def __call__(self, x):
                    o = self.ic(x).astype(mx.float32)
                    if a:
                        o = o - a * (o @ self._u)[..., None] * self._u
                    if self._b:
                        o = o - self._b * self._u
                    return o.astype(x.dtype)
            self.asil[l] = katmanlar[l].mlp
            katmanlar[l].mlp = Sar(katmanlar[l].mlp, u, b_l)

    def kapat(self):
        for l, mlp in self.asil.items():
            self.katmanlar[l].mlp = mlp


def olc(model, tokenizer, onek, kume, etiketler):
    """kume: [(grup, soru)], etiketler: temel etiketler aynı sırada. Döndürür: sayılar ve ayrıntı."""
    sonuc = []
    for (grup, soru), e in zip(kume, etiketler):
        c = uret(model, tokenizer, istem(tokenizer, soru), en_cok=120, onek=onek)
        sonuc.append({"grup": grup, "soru": soru, "temel": e, "arac": bool(arac_cagrilari(c)), "cikti": c[:200]})
    arac = [s for s in sonuc if s["grup"] == "arac"]
    duz = [s for s in sonuc if s["grup"] == "duz"]
    return {"arac_cagri": sum(s["arac"] for s in arac), "arac_toplam": len(arac),
            "duzelen": sum(1 for s in arac if s["temel"] == "kotu" and s["arac"]),
            "bozulan": sum(1 for s in arac if s["temel"] == "iyi" and not s["arac"]),
            "gereksiz": sum(s["arac"] for s in duz), "ayrinti": sonuc}


def main():
    sys.stdout.reconfigure(line_buffering=True)
    t0 = time.time()
    model, tokenizer = model_yukle()
    katmanlar = KATMAN_YOLU(model)
    ozet = json.loads((CIKTI / "02_ozet.json").read_text(encoding="utf-8"))
    H = np.load(CIKTI / "02_durumlar.npy")
    e_gel = np.array(ozet["etiket"])
    gelistirme = [("arac", s) for s in ozet["istemler"]] + [("duz", s) for s in ARAC_ISTEMEYEN]
    onek = OnEk(model, tokenizer, istem(tokenizer, ozet["istemler"][0]), ozet["istemler"][0])
    print(f"hazır {time.time() - t0:.0f} sn")

    # Sınama kümesinin temel etiketleri
    sinama = [("arac", s) for s in SINAMA_ARAC] + [("duz", s) for s in SINAMA_DUZ]
    et_sin, _ = etiketle(model, tokenizer, onek, [s for _, s in sinama])
    et_gel = list(e_gel) + ["duz"] * len(ARAC_ISTEMEYEN)
    et_sin = et_sin[:len(SINAMA_ARAC)] + ["duz"] * len(SINAMA_DUZ)
    print(f"sınama temel: araç {sum(1 for e in et_sin[:len(SINAMA_ARAC)] if e == 'iyi')}/{len(SINAMA_ARAC)}, "
          f"kötü {sum(1 for e in et_sin if e == 'kotu')}, soru {sum(1 for e in et_sin if e == 'soru')} ({time.time() - t0:.0f} sn)")

    # Yönler
    iyi, kotu = H[e_gel == "iyi"], H[e_gel == "kotu"]
    v1 = np.stack([(kotu[:, l].mean(0) - iyi[:, l].mean(0)) / (np.linalg.norm(kotu[:, l].mean(0) - iyi[:, l].mean(0)) + 1e-6) for l in range(H.shape[1])])
    v2 = np.stack([pca_arindir(v1[l], iyi[:, l], k=5) for l in range(H.shape[1])])
    gap = np.array([float(kotu[:, l].mean(0) @ v1[l] - iyi[:, l].mean(0) @ v1[l]) for l in range(H.shape[1])])
    print("katman 27-29 kötü-iyi izdüşüm farkı:", [round(gap[l], 2) for l in KATMANLAR],
          " v1·v2 benzerliği:", [round(float(v1[l] @ v2[l]), 2) for l in KATMANLAR])
    kotu_istemler = [s for s, e in zip(ozet["istemler"], ozet["etiket"]) if e == "kotu"]
    vg = np.zeros_like(v1)
    try:
        for l in KATMANLAR:
            vg[l] = gradyan_yonu(model, tokenizer, onek, katmanlar, l, kotu_istemler)
        # Gradyan log p(tool)'u ARTIRAN yöndür; "anlatma" yönü olarak eksi işaretlisi kullanılır (itme: o - b u = o + b g)
        vg = -vg
        print("gradyan yönü hesaplandı; v1 ile benzerlik:", [round(float(v1[l] @ vg[l]), 2) for l in KATMANLAR], f"({time.time() - t0:.0f} sn)")
        gradyan_var = True
    except Exception as hata:
        print(f"gradyan yönü hesaplanamadı: {type(hata).__name__}: {str(hata)[:160]}")
        gradyan_var = False

    varyantlar = [
        ("temel", None, 0.0, 0.0),
        ("V1 silme a=1.5", v1, 1.5, 0.0),
        ("V2 arındırılmış silme a=1.5", v2, 1.5, 0.0),
        ("V1 itme b=gap", v1, 0.0, gap),
        ("V1 itme b=2gap", v1, 0.0, 2 * gap),
        ("V1 silme a=1.0 + itme b=gap", v1, 1.0, gap),
        ("V2 silme a=1.0 + itme b=gap", v2, 1.0, gap),
    ]
    if gradyan_var:
        varyantlar += [("VG itme b=gap", vg, 0.0, gap), ("VG itme b=2gap", vg, 0.0, 2 * gap), ("VG silme a=1.5", vg, 1.5, 0.0)]
    hepsi = {}
    satirlar = []
    for ad, yon, a, b in varyantlar:
        t = time.time()
        d = MLPDuzenleyici(katmanlar, yon, KATMANLAR, a, b) if yon is not None else None
        try:
            g = olc(model, tokenizer, onek, gelistirme, et_gel)
            s = olc(model, tokenizer, onek, sinama, et_sin)
        finally:
            if d:
                d.kapat()
        hepsi[ad] = {"gelistirme": g, "sinama": s}
        satir = (f"{ad:<32} geliştirme {g['arac_cagri']}/{g['arac_toplam']} (düzelen {g['duzelen']}, bozulan {g['bozulan']}, gereksiz {g['gereksiz']}) | "
                 f"sınama {s['arac_cagri']}/{s['arac_toplam']} (düzelen {s['duzelen']}, bozulan {s['bozulan']}, gereksiz {s['gereksiz']}) [{time.time() - t:.0f} sn]")
        print(satir)
        satirlar.append(satir)
        (CIKTI / "06_sonuc.json").write_text(json.dumps(hepsi, ensure_ascii=False, indent=1), encoding="utf-8")
        (CIKTI / "06_ozet.txt").write_text("\n".join(satirlar), encoding="utf-8")
    np.savez(CIKTI / "06_yonler.npz", v1=v1, v2=v2, vg=vg, gap=gap)


if __name__ == "__main__":
    main()
