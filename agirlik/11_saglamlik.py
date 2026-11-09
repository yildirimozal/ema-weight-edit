#!/usr/bin/env python3
"""Aşama 10, sağlamlık ölçümleri (makale için):
(a) Genel yetenek regresyon testi: 60 denetlenebilir soru (bilgi, hesap, birim, okuma anlama, kısa talimat), araç şemaları
    istemde dururken. Ölçülen: doğruluk, gereksiz araç çağrısı, cevap uzunluğu. Düzenleme genel yeteneği bozdu mu?
(b) Büyük sınama kümesi: 100 yeni araç istemi + 20 yeni düz istem, iki tekrar. Ölçülen: araç çağrısı, gereksiz çağrı.
(c) Az örnekli talimat tabanı: düzenlenmemiş modelin talimatına 5 örnek diyalog eklenir, aynı kümelerde ölçülür.
    ../.venv/bin/python 11_saglamlik.py --model <yol|HF adı> --ad temel [--orneklerle] [--tekrar 2]
Çıktı: cikti/11_<ad>.json, cikti/11_ozet.txt (satır eklenir)."""
import argparse
import json
import re
import sys
import time

from ortak import CIKTI, OnEk, arac_cagrilari, istem, model_yukle, talimat

# ---------- (a) regresyon: (soru, kabul edilen cevap deseni) ----------
REGRESYON = [
    ("Fransa'nın başkenti neresi?", r"paris"), ("Japonya'nın başkenti neresi?", r"tokyo"), ("Almanya'nın başkenti neresi?", r"berlin"),
    ("Dünyanın en büyük okyanusu hangisi?", r"pasifik|büyük okyanus"), ("Suyun kimyasal formülü nedir?", r"h2o|h₂o"),
    ("Işık hızı saniyede yaklaşık kaç kilometredir?", r"300[.\s]?000|300 bin|299[.\s]?792|üç yüz bin"), ("İnsan vücudunda kaç kemik vardır?", r"206|iki yüz altı"),
    ("Türkiye Cumhuriyeti hangi yıl kuruldu?", r"1923"), ("İstanbul'un fethi hangi yıldır?", r"1453"), ("Ay, Dünya'nın etrafında yaklaşık kaç günde döner?", r"27|28|29"),
    ("Güneş sistemindeki en büyük gezegen hangisi?", r"jüpiter"), ("Fotosentez hangi organelde gerçekleşir?", r"kloroplast"),
    ("DNA'nın açılımı nedir?", r"deoksiribo"), ("Bir üçgenin iç açıları toplamı kaç derecedir?", r"180|yüz seksen"),
    ("Pi sayısının ilk üç basamağı nedir?", r"3[.,]14"), ("Mona Lisa'yı kim yaptı?", r"vinci"),
    ("Nutuk'u kim yazdı?", r"atatürk|mustafa kemal"), ("Hangi gezegen Kızıl Gezegen olarak bilinir?", r"mars"),
    ("Everest hangi sıradağlardadır?", r"himalaya"), ("Nil Nehri hangi kıtadadır?", r"afrika"),
    ("Bir dakikada kaç saniye vardır?", r"\b60\b|altmış"), ("Bir yılda kaç hafta vardır?", r"\b52\b|elli iki"),
    # hesap
    ("On yedi kere altı kaç eder?", r"\b102\b|yüz iki"), ("Yüz yirmi dörtün yarısı kaç?", r"\b62\b|altmış iki"),
    ("İki yüzün yüzde on beşi kaç?", r"\b30\b|otuz"), ("Sekiz yüz bölü yirmi beş kaç?", r"\b32\b|otuz iki"),
    ("Kırk beş artı yetmiş sekiz kaç eder?", r"\b123\b|yüz yirmi üç"), ("Dokuzun karesi kaç?", r"\b81\b|seksen bir"),
    ("Yüz altmış dörtün karekökü kaç?", r"12[.,]8|on iki"), ("Üç saat kaç dakikadır?", r"\b180\b|yüz seksen"),
    ("Bir haftada kaç saat vardır?", r"\b168\b|yüz altmış sekiz"), ("Yüz kilometre kaç metredir?", r"100[.\s]?000|yüz bin"),
    ("Beş kilogram kaç gramdır?", r"5[.\s]?000|beş bin"), ("Yirmi beş santigrat derece kaç Fahrenheit'tır?", r"\b77\b|yetmiş yedi"),
    ("Bir düzine kaçtır?", r"\b12\b|on iki"), ("Bir saatte 60 kilometre giden araç 2,5 saatte kaç kilometre gider?", r"\b150\b|yüz elli"),
    ("Kırk sekizin yüzde yirmi beşi kaç?", r"\b12\b|on iki"), ("Otuz altının yarısının yarısı kaç?", r"\b9\b|dokuz"),
    # okuma anlama (kısa metin)
    ("Metin: Ayşe sabah sekizde evden çıktı, dokuzda okula vardı. Soru: Ayşe'nin yolu kaç saat sürdü?", r"\b1\b|bir saat"),
    ("Metin: Masada üç kırmızı, iki mavi kalem var. Soru: Masada toplam kaç kalem var?", r"\b5\b|beş"),
    ("Metin: Ali, Veli'den uzun; Veli, Can'dan uzun. Soru: En kısa kim?", r"can"),
    ("Metin: Toplantı salı günü saat üçte, bir gün ertelendi. Soru: Toplantı hangi gün?", r"çarşamba"),
    ("Metin: Kedi bahçede, köpek evde. Soru: Köpek nerede?", r"ev"),
    ("Metin: Mehmet 12 yaşında, kardeşi ondan 4 yaş küçük. Soru: Kardeşi kaç yaşında?", r"\b8\b|sekiz"),
    ("Metin: Markette elma kilosu 40 lira, armut 60 lira. Soru: Hangisi daha ucuz?", r"elma"),
    ("Metin: Tren 10:15'te kalktı, yolculuk 2 saat 30 dakika sürdü. Soru: Tren kaçta vardı?", r"12[:.]45|on ikiyi kırk beş"),
    ("Metin: Sınıfta 30 öğrenci var, 18'i kız. Soru: Kaç erkek öğrenci var?", r"\b12\b|on iki"),
    ("Metin: Kitap 240 sayfa, Zeynep günde 30 sayfa okuyor. Soru: Kitabı kaç günde bitirir?", r"\b8\b|sekiz"),
    # kısa talimat
    ("Üç tane meyve adı say.", r"(elma|armut|muz|portakal|çilek|üzüm|kiraz|karpuz|kavun|şeftali|erik|kayısı|mandalina|limon|ananas|nar|incir|vişne)"),
    ("Haftanın günlerini sırayla söyle.", r"pazartesi.*salı.*çarşamba.*perşembe.*cuma"),
    ("Bir ile on arasındaki çift sayıları söyle.", r"2.*4.*6.*8"), ("'Kitap' kelimesinin İngilizcesi nedir?", r"\bbook\b"),
    ("'Teşekkür ederim' İngilizcede nasıl söylenir?", r"thank"), ("Türkiye'nin üç büyük şehrini say.", r"istanbul.*(ankara|izmir)|(ankara|izmir).*istanbul"),
    ("Güneş sisteminin ilk dört gezegenini say.", r"merkür.*venüs.*dünya.*mars"), ("Kırmızı ve sarı karışınca hangi renk olur?", r"turuncu"),
    ("Yılın kaçıncı ayı Ağustos?", r"\b8\b|sekizinci"), ("Alfabenin ilk beş harfini söyle.", r"a.*b.*c.*ç.*d"),
    ("Üç tane Türk şehri söyle, hepsi deniz kenarında olsun.", r"(izmir|antalya|trabzon|samsun|mersin|istanbul|bodrum|çanakkale|sinop|ordu|rize|tekirdağ|alanya|muğla|balıkesir|kocaeli|zonguldak|hatay|adana|aydın)"),
    ("Bir cümleyle Ankara'yı tanıt.", r"ankara"),
]

# ---------- (b) büyük sınama: 100 araç istemi ----------
BUYUK_ARAC = [
    "Hatırla: Ahmet'in telefonu 3. katta.", "Unutma: pazartesi bölüm toplantısı var.", "Aklında olsun: kahve makinesi filtresi bitti.",
    "Not al: proje raporu ayın yirmisinde.", "Hatırla, Elif'in savunması cuma on birde.", "Unutma: arabanın muayenesi gelecek ay.",
    "Aklında bulunsun: laboratuvar anahtarını Can aldı.", "Şunu not et: dersin saati on dörde alındı.", "Hatırla: yedek projeksiyon kumandası dolapta.",
    "Unutma, kütüphane kitabını geri vereceğim.", "Aklında olsun: toplantı odası B-204.", "Not al: Dekan ile görüşme perşembe.",
    "Hatırla: öğrenci sayısı bu dönem kırk iki.", "Unutma: bugün su faturası son gün.", "Aklında bulunsun: vize haftası kasımın son haftası.",
    "Hatırla: ofis kapı kodu değil, posta kutusu numarası on üç.", "Not et: yeni asistan Burak.", "Unutma: kongre özeti ayın beşine kadar.",
    "Neleri hatırlıyorsun, kısaca say.", "Hafızandaki toplantı notunu sil.", "Hafızandaki son notu oku.", "Hafızanı listele.",
    "Sonraki slayt.", "Önceki slayt.", "Yedinci slayta git.", "İlk slayta dön.", "Son slayta git.", "Sunumu kapat.", "Slaytı ilerlet.",
    "Bir slayt geri.", "Onuncu slayta geç.", "Sunumun başına git.", "Hafta yedi sunumunu aç.", "Veri madenciliği dersinin hafta iki sunumunu göster.",
    "PISA sunumunu göster.", "Masaüstündeki tez sunumunu aç.", "Belgeler klasöründeki seminer sunumunu aç.", "Hafta on sunumunu projeksiyona aç.",
    "Panoda şu listeyi göster: veri, bilgi, bilgelik.", "Panoda dört madde göster: giriş, yöntem, bulgular, sonuç.", "Panoya şunları yaz: ATP, ADP, NADPH.",
    "Panoyu kapat.", "Panoda cevapları göster.", "Önemli noktaları panoya çıkar: normalizasyon, indeks, anahtar.",
    "Fotosentez konusunda üç soruluk mini sınav aç.", "Hücre zarı hakkında iki soruluk quiz yap.", "Bugün anlattıklarımdan dört soruluk sınav hazırla.",
    "Öğrencilere beş soruluk mini sınav aç, konu SQL birleştirme.", "Mitokondri konusunda kısa bir sınav göster.",
    "Deftere yaz: yedinci hafta, normal formlar anlatıldı.", "Deftere kaydet: sınıf alt sorgularda zorlandı.", "Deftere not düş: ödev tarihi bir hafta uzatıldı.",
    "Deftere ekle: proje gruplarını açıkladım.", "Bugünkü dersi deftere kaydet: fotosentez ve hücre solunumu.", "Defterde normal formlar geçen kaydı bul.",
    "Defterde geçen haftaki dersi ara.", "Defterde proje ile ilgili kayıt var mı bak.",
    "Deneme klasöründe kaç txt var?", "Belgeler klasöründe kaç pdf var?", "İndirilenler'de kaç dosya var?", "Masaüstünde kaç klasör var?",
    "Deneme klasöründeki md dosyalarını say.", "Belgeler'de docx dosyası var mı?", "Masaüstünde adında rapor geçen dosya var mı?",
    "İndirilenler'de en son indirilen dosya ne?", "Deneme klasöründe papatya kelimesi geçen dosya var mı?", "notlar.txt dosyasında ne yazıyor?",
    "notlar.txt dosyasının ilk satırını oku.", "Deneme klasöründeki a.txt dosyasını oku.", "Deneme klasöründeki txt dosyalarının toplam satır sayısı kaç?",
    "Masaüstündeki bütçe dosyasını aç.", "Deneme klasöründeki en büyük dosya hangisi?", "Belgeler'de bu yıl değişen dosyaları listele.",
    "Çalışma klasörüne gorevler.txt yaz, içine üç görev yaz.", "Masaüstüne not.txt oluştur, içine merhaba yaz.", "ozet.txt dosyasına yeni satır ekle: ders iptal.",
    "Çalışma klasöründe liste.csv oluştur, içine ad,soyad yaz.", "Deneme klasörüne yeni.txt yaz, içinde deneme yazsın.", "notlar.txt dosyasının sonuna bugünün tarihini ekle.",
    "Çalışma klasörüne rapor.md oluştur, başlık olarak Rapor yaz.", "ozet.txt dosyasındaki 'toplantı' kelimesini 'görüşme' yap.",
    "Bir saat sonrası saat kaç olur, zaman aracıyla bak.", "Yarın saat dokuzun tam zamanını zaman aracıyla ver.", "Kırk dakika sonrasını zaman aracıyla hesapla.",
    "Haftaya salı saat onun tarihini zaman aracıyla bul.", "Şu anki saati zaman aracıyla söyle.",
    "Telefonuma notlar.txt dosyasını gönder.", "Telefonuma şu mesajı gönder: toplantı başlıyor.", "Deneme klasöründeki a.txt dosyasını telefonuma yolla.",
    "ozet.txt dosyasının gerçekten yazıldığını doğrula.", "Hatırlatmanın kurulduğunu doğrula.", "Dosyanın var olduğunu dogrula aracıyla kontrol et.",
    "Masaüstündeki sunumu bul ve aç.", "Deneme klasöründe iki geçen dosya var mı bak.", "Belgeler klasöründe sunum dosyalarını listele.",
    "Hafızaya ekle: en sevdiğim renk mavi.", "Unutma: cumartesi veli toplantısı.", "Slayt beşe git.",
]
BUYUK_DUZ = [
    "Kaç kıta var?", "Suyun kaynama noktası kaç derece?", "Bugün günlerden ne?", "İki kere on iki kaç eder?",
    "Fotosentezde oksijen nereden çıkar, tek cümle.", "Nasılsın bugün?", "Ankara'nın plaka kodu kaç?", "Bana kısa bir tekerleme söyle.",
    "En sevdiğin renk ne?", "Bir dakikada kaç saniye var?", "Türkiye'nin en uzun nehri hangisi?", "Bir fıkra anlat, kısa olsun.",
    "Beş artı yedi kaç?", "Hangi mevsimdeyiz?", "Kahve mi çay mı, sence?", "Mitokondri ne iş yapar, iki cümle.",
    "Dünya Güneş'in etrafında kaç günde döner?", "Bana bir iltifat et.", "Üç tane renk say.", "Günaydın demek için İngilizce ne denir?",
]

# ---------- (c) az örnekli talimat ----------
ORNEKLER = """

Örnekler (aracı aynı cevapta çağır):
Kullanıcı: Unutma: cuma günü bölüm toplantısı var.
Sen: <tool_call><function=hafiza><parameter=eylem>ekle</parameter><parameter=metin>Cuma günü bölüm toplantısı var</parameter></function></tool_call>
Kullanıcı: İlk slayta git.
Sen: <tool_call><function=sunum><parameter=eylem>ilk</parameter></function></tool_call>
Kullanıcı: Bugünkü dersi deftere yaz: fotosentez anlatıldı.
Sen: <tool_call><function=defter><parameter=eylem>yaz</parameter><parameter=baslik>Fotosentez dersi</parameter><parameter=metin>Bugün fotosentez anlatıldı.</parameter></function></tool_call>
Kullanıcı: Çalışma klasörüne ozet.txt yaz, içinde Merhaba yazsın.
Sen: <tool_call><function=Write><parameter=file_path>ozet.txt</parameter><parameter=content>Merhaba</parameter></function></tool_call>
Kullanıcı: Panoda cevapları göster.
Sen: <tool_call><function=pano><parameter=eylem>cevaplar</parameter></function></tool_call>"""


def dogru_mu(cevap, desen):
    return re.search(desen, cevap.lower()) is not None


def main():
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--ad", required=True)
    p.add_argument("--orneklerle", action="store_true")
    p.add_argument("--tekrar", type=int, default=2)
    arg = p.parse_args()
    t0 = time.time()
    model, tokenizer = model_yukle(arg.model)
    sistem = talimat() + (ORNEKLER if arg.orneklerle else "")
    onek = OnEk(model, tokenizer, istem(tokenizer, REGRESYON[0][0], sistem=sistem), REGRESYON[0][0])
    print(f"{arg.ad}: hazır {time.time() - t0:.0f} sn, ön ek {len(onek.tokens)} token")

    # (a) regresyon
    reg = []
    for soru, desen in REGRESYON:
        c = uret_(model, tokenizer, istem(tokenizer, soru, sistem=sistem), onek)
        reg.append({"soru": soru, "cevap": c[:300], "dogru": dogru_mu(c, desen), "arac": bool(arac_cagrilari(c)), "uzunluk": len(c)})
    dogru = sum(r["dogru"] for r in reg)
    gereksiz = sum(r["arac"] for r in reg)
    print(f"  regresyon: doğru {dogru}/{len(reg)}, gereksiz araç {gereksiz}, ortalama uzunluk {sum(r['uzunluk'] for r in reg) / len(reg):.0f} harf ({time.time() - t0:.0f} sn)")

    # (b) büyük sınama, tekrarlı
    buyuk = []
    for tekrar in range(arg.tekrar):
        arac_sayi = 0
        duz_gereksiz = 0
        ayrinti = []
        for soru in BUYUK_ARAC:
            c = uret_(model, tokenizer, istem(tokenizer, soru, sistem=sistem), onek)
            a = bool(arac_cagrilari(c))
            arac_sayi += a
            ayrinti.append({"grup": "arac", "soru": soru, "arac": a, "cikti": c[:160]})
        for soru in BUYUK_DUZ:
            c = uret_(model, tokenizer, istem(tokenizer, soru, sistem=sistem), onek)
            a = bool(arac_cagrilari(c))
            duz_gereksiz += a
            ayrinti.append({"grup": "duz", "soru": soru, "arac": a, "cikti": c[:160]})
        buyuk.append({"arac": arac_sayi, "arac_toplam": len(BUYUK_ARAC), "gereksiz": duz_gereksiz, "duz_toplam": len(BUYUK_DUZ), "ayrinti": ayrinti})
        print(f"  büyük sınama tekrar {tekrar + 1}: araç {arac_sayi}/{len(BUYUK_ARAC)}, gereksiz {duz_gereksiz}/{len(BUYUK_DUZ)} ({time.time() - t0:.0f} sn)")

    (CIKTI / f"11_{arg.ad}.json").write_text(json.dumps({"ayar": vars(arg), "regresyon": reg, "buyuk": buyuk}, ensure_ascii=False, indent=1), encoding="utf-8")
    satir = (f"{arg.ad:<22} regresyon {dogru}/{len(reg)} (gereksiz araç {gereksiz}) | büyük sınama araç "
             + ", ".join(f"{b['arac']}/{b['arac_toplam']}" for b in buyuk) + " | gereksiz " + ", ".join(f"{b['gereksiz']}/{b['duz_toplam']}" for b in buyuk))
    print(satir)
    with open(CIKTI / "11_ozet.txt", "a", encoding="utf-8") as f:
        f.write(satir + "\n")


def uret_(model, tokenizer, metin, onek):
    from ortak import uret
    return uret(model, tokenizer, metin, en_cok=160, onek=onek)


if __name__ == "__main__":
    main()
