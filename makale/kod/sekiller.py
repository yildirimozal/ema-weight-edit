#!/usr/bin/env python3
"""Makale şekilleri (gri tonlama, Times, tam çerçeve, içe çentik; ~/.claude/CLAUDE.md kuralları).
Veriler: ../veri/ (kıyaslama sonuçları, 02_yonler.npz, 06/08/09 özetleri). Çalıştır: sahne_asistani/.venv/bin/python sekiller.py"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

KOK = Path(__file__).resolve().parent.parent
VERI, SEKIL = KOK / "veri", KOK / "sekiller"
SEKIL.mkdir(exist_ok=True)
KOYU, ORTA, ACIK = "#404040", "#8c8c8c", "#ffffff"

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"], "font.size": 9,
    "axes.labelweight": "bold", "axes.titleweight": "bold", "axes.titlesize": 9, "axes.labelsize": 9,
    "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True, "ytick.right": True,
    "axes.grid": False, "legend.frameon": False, "legend.fontsize": 8, "pdf.fonttype": 42, "ps.fonttype": 42,
})


def kaydet(fig, ad):
    fig.savefig(SEKIL / f"{ad}.png", dpi=300, bbox_inches="tight")
    fig.savefig(SEKIL / f"{ad}.pdf", bbox_inches="tight")
    plt.close(fig)
    print("yazıldı", ad)


def yukle(ad):
    return json.loads((VERI / ad).read_text(encoding="utf-8"))


# ---------- Şekil 1: motor kıyaslaması (başarı ve ilk kelime gecikmesi) ----------
def sekil1():
    s1139, s1455, s1824 = yukle("sonuc_20261108_1139.json"), yukle("sonuc_20261108_1455.json"), yukle("sonuc_20261108_1824.json")
    s1529 = yukle("sonuc_20261108_1529.json")
    s2345 = yukle("sonuc_20261108_2345.json")
    oturum_ici = yukle("ema2_oturum_ici_gecikme.json")   # düzenlenmiş model: aynı oturumda 15 soru, ilk kelime süreleri
    motorlar = [
        ("Claude Sonnet (cloud)", s1139["claude:sonnet"], KOYU, ""),
        ("Qwen3.5 4B, edited (ours)", s2345["yerel:~/sahne_asistani/agirlik/cikti/model_ema2"], ORTA, "////"),
        ("Qwen3.5 4B", s1455["yerel:qwen3.5:4b"], ORTA, ""),
        ("Qwen3.5 9B", s1455["yerel:qwen3.5:9b"], ORTA, ""),
        ("Qwen3.5 4B abliterated", s1529["yerel:huihui_ai/qwen3.5-abliterated:4B"], ACIK, "////"),
        ("Qwen2.5 7B", s1139["yerel:qwen2.5:7b"], ACIK, ""),
    ]
    # Claude'un "uydurmama" görevi: denetim koşumdan sonra düzeltildi ("özetleyeyim mi" sorusu ceza almasın), rapordaki gibi geçer
    for s in s1139["claude:sonnet"]:
        if s["gorev"] == "uydurmama":
            s["basarili"] = True
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.9), gridspec_kw={"width_ratios": [1.15, 1]})
    y = np.arange(len(motorlar))[::-1]
    for yi, (ad, l, renk, tarama) in zip(y, motorlar):
        basari = sum(s["basarili"] for s in l)
        a.barh(yi, basari, color=renk, edgecolor="black", hatch=tarama, height=0.62)
        a.text(basari + 0.2, yi, f"{basari}/15", va="center", fontsize=8)
    a.set_yticks(y)
    a.set_yticklabels([m[0] for m in motorlar])
    a.set_xlim(0, 17)
    a.set_xlabel("Tasks passed (of 15)")
    a.set_title("(a) Task success")
    # (b) ilk kelime: görev başına medyan; düzenlenmiş model için taze oturum (ölçülen) ve aynı oturumda ardışık soru (0,45 sn)
    for yi, (ad, l, renk, tarama) in zip(y, motorlar):
        if "edited" in ad:
            ilk = [x for x in oturum_ici["ilk"] if x]   # taze oturum düzeneği yerine oturum içi ölçüm (metinde açıklanır)
        else:
            ilk = [s["ilk"] for s in l if s["ilk"] is not None]
        med = float(np.median(ilk))
        b.barh(yi, med, color=renk, edgecolor="black", hatch=tarama, height=0.62)
        b.text(med * 1.15, yi, f"{med:.1f} s", va="center", fontsize=8)
    b.set_xscale("log")
    b.set_xlim(0.3, 120)
    b.set_yticks(y)
    b.set_yticklabels([])
    b.set_xlabel("Median time to first word (s, log scale)")
    b.set_title("(b) Latency")
    fig.tight_layout()
    kaydet(fig, "sekil1_motorlar")


# ---------- Şekil 2: katman başına ayrışma ----------
def sekil2():
    d = np.load(VERI / "02_yonler.npz")["ayrisma"]
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    ax.plot(range(len(d)), d, color=KOYU, marker="o", markersize=3, linewidth=1.2)
    for l in (27, 28, 29):
        ax.plot(l, d[l], marker="s", color="black", markersize=5)
    ax.axvspan(26.5, 29.5, color="#dddddd", zorder=0)
    ax.set_xlabel("Layer")
    ax.set_ylabel("Separation d (narrate vs. call)")
    ax.set_xlim(-0.5, 31.5)
    ax.set_ylim(0, max(d) * 1.15)
    ax.text(28, max(d) * 0.3, "edited\nlayers", ha="center", va="center", fontsize=8)
    fig.tight_layout()
    kaydet(fig, "sekil2_ayrisma")


# ---------- Şekil 3: müdahale varyantları, geliştirme ve sınama kümeleri ----------
def sekil3(varyantlar):
    """varyantlar: [(ad, gel_cagri, gel_gereksiz, sin_cagri, sin_gereksiz)] (gel 68, sin 40, düz 8)."""
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    y = np.arange(len(varyantlar))[::-1]
    h = 0.36
    for yi, (ad, g, gg, s, sg) in zip(y, varyantlar):
        ax.barh(yi + h / 2, 100 * g / 68, height=h, color=KOYU, edgecolor="black")
        ax.text(100 * g / 68 + 0.8, yi + h / 2, f"{g}/68", va="center", fontsize=7.5)
        if s is None:
            ax.text(0.8, yi - h / 2, "held-out not measured", va="center", fontsize=7, color=KOYU, style="italic")
            ax.text(118, yi, f"{gg} / n/a", va="center", ha="center", fontsize=7.5)
        else:
            ax.barh(yi - h / 2, 100 * s / 40, height=h, color=ACIK, edgecolor="black", hatch="////")
            ax.text(100 * s / 40 + 0.8, yi - h / 2, f"{s}/40", va="center", fontsize=7.5)
            ax.text(118, yi, f"{gg} / {sg}", va="center", ha="center", fontsize=7.5)
    ax.text(118, len(varyantlar) - 0.55, "spurious calls\n(dev / held-out, of 8)", ha="center", va="bottom", fontsize=7.5, fontweight="bold")
    ax.set_yticks(y)
    ax.set_yticklabels([v[0] for v in varyantlar])
    ax.set_xlim(0, 133)
    ax.set_ylim(-0.7, len(varyantlar) + 0.9)
    ax.set_xlabel("Tool-requiring prompts answered with a tool call (%)")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=KOYU, ec="black"), plt.Rectangle((0, 0), 1, 1, color=ACIK, ec="black", hatch="////")],
              labels=["development set (68 prompts, used to derive the direction)", "held-out set (40 unseen prompts)"],
              loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    fig.tight_layout()
    kaydet(fig, "sekil3_varyantlar")


# ---------- Şekil 4: derleme şiddeti, çalışma anı ve 4 bit ----------
def sekil4():
    a_ = [1.0, 1.5, 2.0]
    calisma = [59, None, 60]      # 04: mlp a=1.0 → 59, a=2.0 → 60 (a=1.5 çalışma anında ölçülmedi)
    derlenmis = [56, 59, 59]      # 05: 4 bite yeniden sıkıştırılmış
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    ax.axhline(52, color=ORTA, linestyle="--", linewidth=1)
    ax.text(2.02, 52.3, "baseline 52", fontsize=7.5, color=KOYU, ha="right")
    ax.plot([a for a, c in zip(a_, calisma) if c], [c for c in calisma if c], marker="o", color=KOYU, label="runtime (float)")
    ax.plot(a_, derlenmis, marker="s", color="black", linestyle=":", label="compiled, 4-bit")
    ax.set_xlabel("Edit strength a")
    ax.set_ylabel("Tool calls (of 68)")
    ax.set_xticks(a_)
    ax.set_ylim(50, 62)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=2)
    fig.tight_layout()
    kaydet(fig, "sekil4_derleme")


if __name__ == "__main__":
    sekil1()
    sekil2()
    sekil4()
    varyantlar = [
        ("Baseline (no edit)", 52, 1, 30, 0),
        ("Ablate u, residual, decision + all generated", 50, 1, 29, 0),
        ("Ablate u, residual, decision position only", 56, 1, 29, 0),
        ("Ablate u from MLP output, a=1.5", 59, 1, 33, 0),
        ("Ablate PCA-cleaned u, a=1.5", 53, 1, 33, 0),
        ("Push along u, b=gap", 68, 3, 40, 3),
        ("Push along u, b=0.5 gap", 67, 0, 39, 0),
        ("Ablate + push (cleaned u)", 68, 1, 40, 2),
        ("Push via 1 constant channel, b=0.5 gap", 67, 0, 40, 2),
        ("Push via 10 channels, b=0.5 gap (emulated)", 67, 0, 40, 0),
        ("Push via 10 channels, compiled, 8-bit", 68, 0, 40, 0),
    ]
    sekil3(varyantlar)
