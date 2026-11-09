#!/usr/bin/env python3
"""Kıyaslama için Ema'nın araçlarının sahtesi (kiyasla.py kullanır).

Araç tanımları gerçek (arac_sunucusu.ARACLAR), ama sunum açmak, hafızaya yazmak, pano göstermek gibi işler yapılmaz:
çağrı bir günlük dosyasına yazılır ve modele kısa, inandırıcı bir sonuç dönülür. zaman aracı gerçek hesabı yapar (yan
etkisi yok). Bu dosya hem Claude Code'a MCP sunucusu olarak verilir (stdio) hem de yerel motorun çalıştırıcısı olarak
içe aktarılır. SAHTE_GUNLUK ortam değişkeni günlük dosyasının yolu.
"""
import json
import os
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import arac_sunucusu  # noqa: E402
import zaman_araci  # noqa: E402

SAHTE_CEVAP = {
    "sunum": "Sunum açıldı ve tam ekranda gösteriliyor.",
    "slayt": "Slayt 3: Fotosentez. Bitkiler ışık enerjisini kimyasal enerjiye çevirir. Kloroplast, klorofil, glikoz ve oksijen.",
    "pano": "Pano projeksiyonda gösterildi.",
    "quiz": "Quiz oluşturuldu, QR kod projeksiyonda.",
    "hafiza": "Not eklendi.",
    "defter": "Deftere yazıldı.",
    "dogrula": "Doğrulandı: istenen şey var.",
    "telefon": "Telefona gönderildi.",
    "ekran": "(Ekran görüntüsü alındı.)",
    "bilgisayar": "Yapıldı.",
    "claude_oturumlari": "Oturum yok.",
    "oturuma_is_ver": "İş tamamlandı.",
    "kendini_gelistir": "Çalışma kopyası hazır.",
}


def sahte_cevap(ad, girdi, gunluk=None):
    """(metin, hata mı). Çağrıyı günlüğe yazar."""
    gunluk = gunluk or os.environ.get("SAHTE_GUNLUK")
    if gunluk:
        with open(gunluk, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ad": ad, "girdi": girdi}, ensure_ascii=False) + "\n")
    if ad == "zaman":
        tamam, metin = zaman_araci.hesapla(girdi)
        return metin, not tamam
    if ad == "hafiza" and girdi.get("eylem") == "listele":
        return "Hafızada not yok.", False
    if ad in SAHTE_CEVAP:
        return SAHTE_CEVAP[ad], False
    return "Böyle bir araç yok.", True


_asil_isle = arac_sunucusu.isle


def isle(yontem, params):
    if yontem != "tools/call":
        return _asil_isle(yontem, params)
    metin, hata = sahte_cevap(params.get("name"), params.get("arguments") or {})
    return {"content": [{"type": "text", "text": metin}], "isError": hata}


if __name__ == "__main__":
    arac_sunucusu.isle = isle
    arac_sunucusu.main()
