#!/usr/bin/env python3
"""Ağırlık uzayı deneyi için ortak parçalar: MLX modelini yükleme, Ema'nın talimatı ve araç şemalarıyla sohbet istemi
kurma, üretim ve araç çağrısı ayrıştırma (8 Kasım 2026).

Deneyin amacı: Qwen3.5 4B'nin "açıyorum / not ettim" deyip aracı çağırmama takılmasını, modelin iç durumunda bir yön
olarak bulup (Astra'nın yaptığı gibi) önce çalışma anında bastırmak, işe yararsa ağırlığa derlemek. Bilgi eklemez.
"""
import copy
import json
import re
import sys
from pathlib import Path

import mlx.core as mx
import mlx.nn as mx_nn
from mlx_lm import load
from mlx_lm.generate import generate_step
from mlx_lm.models.cache import make_prompt_cache

KOK = Path(__file__).resolve().parent  # bu paket: betikler, dondurulmuş talimat ve araç şemaları, cikti/
MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"
CIKTI = KOK / "cikti"
# Qwen3.5 araç çağrısı biçimi: <tool_call><function=AD><parameter=ALAN>değer</parameter>...</function></tool_call>
# (Qwen2.5'teki JSON biçimi de kabul edilir)
ARAC_CAGRISI = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.S)
ISLEV = re.compile(r"<function=([\w.\-]+)>", re.S)
PARAMETRE = re.compile(r"<parameter=([\w.\-]+)>\s*(.*?)\s*</parameter>", re.S)


def talimat():
    """Ema'nın yerel talimatı: asistanın ürettiği metnin dondurulmuş kopyası (talimat.txt, 9 Kasım 2026)."""
    return (KOK / "talimat.txt").read_text(encoding="utf-8")


def araclar():
    """Yerel motora verilen 18 araç şeması (8 yerleşik + 10 Ema aracı), OpenAI biçiminde: araclar.json'dan."""
    return json.loads((KOK / "araclar.json").read_text(encoding="utf-8"))


def model_yukle(yol=MODEL):
    model, tokenizer = load(yol)
    return model, tokenizer


def istem(tokenizer, soru, sistem=None, araclar_=None, gecmis=()):
    mesajlar = [{"role": "system", "content": sistem or talimat()}, *gecmis, {"role": "user", "content": soru}]
    try:
        return tokenizer.apply_chat_template(mesajlar, tools=araclar_ if araclar_ is not None else araclar(),
                                             add_generation_prompt=True, tokenize=False, enable_thinking=False)
    except TypeError:
        return tokenizer.apply_chat_template(mesajlar, tools=araclar_ if araclar_ is not None else araclar(),
                                             add_generation_prompt=True, tokenize=False)


class Sarmal(mx_nn.Module):
    """Bir dekoder katmanını sarar: çıkışı bir işlevden geçirir (kaydetmek ya da yönlendirmek için). Python çağrıyı
    sınıf üzerinden çözdüğü için örneğe __call__ atamak işe yaramaz; katman listesindeki nesne değiştirilir."""

    def __init__(self, katman, islev):
        super().__init__()
        self.katman = katman
        self.islev = islev
        self.is_linear = katman.is_linear  # model döngüsü maske seçerken buna bakıyor

    def __call__(self, x, mask=None, cache=None):
        return self.islev(self.katman(x, mask=mask, cache=cache))


def katmanlari_sar(katmanlar, islevler):
    """islevler: {katman no: işlev}. Asılları döndürür (katmanlari_coz ile geri konur)."""
    asil = {}
    for i, f in islevler.items():
        asil[i] = katmanlar[i]
        katmanlar[i] = Sarmal(katmanlar[i], f)
    return asil


def katmanlari_coz(katmanlar, asil):
    for i, k in asil.items():
        katmanlar[i] = k


class OnEk:
    """Ortak ön ek (sistem talimatı + araç şemaları, ~4 bin token) bir kez işlenir, her soru için kopyalanır.
    Ollama bunu kendi yapıyor; burada 20 saniyelik istem işlemesi birkaç yüz milisaniyeye iner."""

    def __init__(self, model, tokenizer, tam_istem_ornegi, soru_ornegi):
        # Şablon çıktısında sorunun geçtiği yere kadar olan kısım ön ektir
        kes = tam_istem_ornegi.index(soru_ornegi)
        self.onek = tam_istem_ornegi[:kes]
        self.model = model
        self.tokens = tokenizer.encode(self.onek, add_special_tokens=False)
        self.cache = make_prompt_cache(model)
        girdi = mx.array(self.tokens)
        # Ön eki işle (son token hariç; generate_step kalanını işler)
        for i in range(0, len(girdi) - 1, 512):
            parca = girdi[i:min(i + 512, len(girdi) - 1)]
            self.model(parca[None], cache=self.cache)
            mx.eval([c.state for c in self.cache])
        self.son = len(girdi) - 1

    def kopya(self):
        return copy.deepcopy(self.cache)

    def kalan(self, tokenizer, tam_istem):
        """Ön ek dışında kalan tokenler (önek'in son tokeni dahil, ön ek sınırında bölünme olmasın diye metinden)."""
        assert tam_istem.startswith(self.onek), "istem ön eke uymuyor"
        return tokenizer.encode(tam_istem, add_special_tokens=False)[self.son:]


def uret(model, tokenizer, metin, en_cok=200, onek=None, kanca=None):
    """Açgözlü üretim (sıcaklık 0). onek: OnEk önbelleği. kanca: üretim sırasında modele takılı yönlendirme (dışarıda kurulur)."""
    if onek is not None:
        girdi = mx.array(onek.kalan(tokenizer, metin))
        cache = onek.kopya()
    else:
        girdi = mx.array(tokenizer.encode(metin, add_special_tokens=False))
        cache = None
    parcalar = []
    for token, _ in generate_step(girdi, model, max_tokens=en_cok, prompt_cache=cache):
        t = int(token)
        if t in tokenizer.eos_token_ids:
            break
        parcalar.append(t)
    return tokenizer.decode(parcalar)


def arac_cagrilari(cikti):
    sonuc = []
    for m in ARAC_CAGRISI.finditer(cikti):
        govde = m.group(1)
        f = ISLEV.search(govde)
        if f:
            sonuc.append({"name": f.group(1), "arguments": {k: v for k, v in PARAMETRE.findall(govde)}})
            continue
        try:
            sonuc.append(json.loads(govde.strip()))
        except ValueError:
            sonuc.append({"name": "_ham", "arguments": {"metin": govde[:200]}})
    return sonuc


# Kıyaslamadaki görev istemleri: araç gerektirenler ve gerektirmeyenler
ARAC_ISTEYEN = [
    "PISA sunumunu aç.",
    "Sonraki slayta geç.",
    "Hatırla: ofis anahtarım masanın sol çekmecesinde.",
    "Panoda şu listeyi göster: fotosentez, hücre, mitokondri.",
    "Öğrencilere fotosentez konusunda üç soruluk bir mini sınav aç.",
    "Deneme klasöründe kaç tane txt dosyası var?",
    "notlar.txt dosyasında anahtar kelime olarak ne yazıyor?",
    "Masaüstündeki rapor_2031.docx dosyasını özetle.",
    "Çalışma klasörüne ozet.txt adında bir dosya yaz, içinde Merhaba Ema yazsın.",
    "Unutma: cuma günü bölüm toplantısı var.",
    "Hafta beş sunumunu göster.",
    "Önemli noktaları panoda göster: kloroplast, klorofil, glikoz.",
    "Belgeler klasöründe kaç pdf var?",
    "Beşinci slayta git.",
    "Masaüstünde adında bütçe geçen bir dosya var mı?",
    "Bugün anlattıklarımızdan üç soruluk bir quiz hazırla.",
    "Aklında olsun: Ahmet Hoca'nın odası üçüncü katta.",
    "Not al: proje teslimi on beş aralık.",
    "Bunu hatırla, şifremi değil, arabamın plakası otuz dört.",
    "Unutma, yarın saat onda tez savunması var.",
    "Hafızana ekle: en sevdiğim kahve filtre kahve.",
    "Önceki slayta dön.",
    "İlk slayta git.",
    "Sunumu kapat.",
    "Panoyu kapat.",
    "Panoda cevapları göster.",
    "Masaüstündeki notlar dosyasını aç.",
    "İndirilenler klasöründe en son indirdiğim dosya ne?",
    "Bu klasördeki dosyaların adlarını söyle.",
    "ozet.txt dosyasına bir satır ekle: toplantı ertelendi.",
    "Neleri hatırlıyorsun?",
    "Hafızandaki üçüncü notu sil.",
    "Veritabanı dersinin hafta üç sunumunu aç.",
    "Deneme klasöründe içinde papatya geçen dosya var mı?",
    "Şu anki saati zaman aracıyla söyle.",
    "Kırk dakika sonrası saat kaç olur, zaman aracıyla hesapla.",
    "Bugünkü dersin özetini deftere yaz: fotosentez ve hücre solunumu anlatıldı.",
    "Defterde geçen hafta ne anlattığımı ara.",
    "Çalışma klasöründe rapor.txt adında dosya oluştur, içine deneme yaz.",
]
ARAC_ISTEMEYEN = [
    "Türkiye'nin başkenti neresi?",
    "Yarın haftanın hangi günü?",
    "Bir dönem on dört hafta, haftada üç saat dersim var, toplam kaç saat eder?",
    "Fotosentez nedir, iki cümleyle anlat.",
    "Günaydın, nasılsın?",
    "Mitokondri ne iş yapar?",
    "İstanbul'un nüfusu yaklaşık kaç?",
    "Bana kısa bir espri yap.",
]
