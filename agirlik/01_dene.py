#!/usr/bin/env python3
"""Aşama 1, yapılabilirlik ve takılma envanteri: MLX modeli yüklenir, Ema'nın talimatı ve araçlarıyla istemler
çalıştırılır (ön ek önbellekli, açgözlü); her istem için araç çağrısı üretip üretmediği kaydedilir.
Çıktı: agirlik/cikti/01_dene.json. Araç isteyip de araç çağrılmayan istemler sonraki aşamanın "kötü" örnekleridir."""
import json
import time

from ortak import ARAC_ISTEMEYEN, ARAC_ISTEYEN, CIKTI, OnEk, arac_cagrilari, istem, model_yukle, uret

t0 = time.time()
model, tokenizer = model_yukle()
print(f"model yüklendi {time.time() - t0:.1f} sn")
t0 = time.time()
onek = OnEk(model, tokenizer, istem(tokenizer, ARAC_ISTEYEN[0]), ARAC_ISTEYEN[0])
print(f"ön ek işlendi: {len(onek.tokens)} token, {time.time() - t0:.1f} sn")
sonuc = []
for grup, liste in (("arac", ARAC_ISTEYEN), ("duz", ARAC_ISTEMEYEN)):
    for soru in liste:
        t = time.time()
        cikti = uret(model, tokenizer, istem(tokenizer, soru), en_cok=160, onek=onek)
        cagrilar = arac_cagrilari(cikti)
        sonuc.append({"grup": grup, "soru": soru, "arac": [c.get("name") for c in cagrilar], "cikti": cikti[:500], "sure": round(time.time() - t, 1)})
        print(f"  {grup:4} {'ARAÇ ' + ','.join(c.get('name') or '' for c in cagrilar) if cagrilar else 'metin':<22} {time.time() - t:5.1f} sn | "
              f"{soru[:42]:<42} | {cikti[:60].replace(chr(10), ' ')}")
CIKTI.mkdir(exist_ok=True)
(CIKTI / "01_dene.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")
a = [s for s in sonuc if s["grup"] == "arac"]
d = [s for s in sonuc if s["grup"] == "duz"]
print(f"\naraç isteyen {len(a)} istemin {sum(1 for s in a if s['arac'])}'inde araç çağrıldı; "
      f"araç istemeyen {len(d)} istemin {sum(1 for s in d if s['arac'])}'inde gereksiz araç çağrıldı")
print("araçsız kalanlar:", [s["soru"] for s in a if not s["arac"]])
