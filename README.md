# Pushing a 4B On-Device Assistant to Act

Code, prompt sets, result files and paper source for

> Özal Yıldırım. *Pushing a 4B On-Device Assistant to Act: Weight-Space Editing of Tool-Use Hesitation in Qwen3.5.* 2026. `makale/makale.pdf`

The paper studies a failure of small local models in a tool-using voice assistant (Ema, macOS): asked to act, the model announces the action ("Noted.", "Opening the presentation.") and never emits the tool call. A single "narration" direction is found in the residual stream of Qwen3.5 4B, and the hesitation is removed by editing three MLP output matrices directly, with no training. The best edit (a constant push compiled through ten near-constant channels per layer) calls a tool on 96 of 98 unseen prompts against 84 for the unedited model, with no change on general questions.

## Layout

| Folder | Contents |
|---|---|
| `agirlik/` | The experiment scripts, numbered in order of execution (`01_dene.py` … `16_nicemleme.py`), `ortak.py` (shared code: prefix cache, generation, tool-call parser, prompt sets), the frozen inputs the scripts took from the assistant (`talimat.txt` system instruction, `araclar.json` 18 tool schemas, `izin.py` permission function) and `cikti/` with every result file the paper reads (JSON, NumPy, Markdown). |
| `makale/` | `makale.tex`, `kaynaklar.bib`, `makale.pdf`, `kod/sekiller.py` (all figures from `veri/`), `veri/` (copies of the result files), `sekiller/` (PNG and PDF). |
| `kiyaslama/` | The fifteen-task assistant benchmark (`kiyasla.py`, fake tool layer `testler/sahte_sahne.py`, `birlestir.py`, over-refusal test `reduz_testi.py`) and its merged report `rapor.md`. These scripts run inside the assistant and are included for reference, not as a standalone harness. |

Prompt sets are embedded in the scripts: 68 development prompts in `ortak.py` (`ARAC_ISTEYEN`, `ARAC_ISTEMEYEN`), the 40 + 8 held-out prompts in `06_yon_varyantlari.py` (`SINAMA_ARAC`, `SINAMA_DUZ`), the 98 + 20 held-out prompts and 60 regression questions in `11_saglamlik.py` (`BUYUK_ARAC`, `BUYUK_DUZ`, `REGRESYON`). All prompts are Turkish.

## Reproducing

Hardware and software used: Apple M4, 16 GB, macOS 26.3.1, Python 3.14, MLX 0.32.4, mlx-lm 0.32.2 (`requirements.txt`). The unedited model is `mlx-community/Qwen3.5-4B-MLX-4bit` (revision `32f3e8ec`), downloaded from Hugging Face on first use.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd agirlik
../.venv/bin/python 02_aktivasyon.py          # activations, labels, directions -> cikti/02_*
../.venv/bin/python 06_yon_varyantlari.py     # inference-time variants, held-out set -> cikti/06_*
../.venv/bin/python 09_coklu_kanal.py         # near-constant channels for the push -> cikti/09_kanallar.json
../.venv/bin/python 10_derle_itme.py --ayar "v1 itme 10 kanal b=0.5gap" --ad ema2   # compiled push model -> cikti/model_ema2/
../.venv/bin/python 05_derle.py --a 1.5       # compiled ablation model -> cikti/model_ema1/
../.venv/bin/python 11_saglamlik.py --model cikti/model_ema2 --ad itme_ema2          # 98 + 20 held-out, 60 regression
../.venv/bin/python 13_hakem.py --model cikti/model_ema2 --ad itme                    # right-tool, permission, direction sensitivity
../.venv/bin/python 15_kontrol.py             # position sweep, random directions, reverse push, channel stability
../.venv/bin/python 16_nicemleme.py           # edit size against the 4-bit quantization step
../.venv/bin/python 14_istatistik.py          # Wilson intervals, McNemar tests -> cikti/14_istatistik.md
cd ../makale && ../.venv/bin/python kod/sekiller.py   # figures
```

Each script's docstring states its inputs, arguments and outputs. Decoding is greedy throughout. Greedy decoding with copied prefix caches is not bit-exact across runs on this hardware: the development and 40-prompt held-out counts can move by one or two prompts between runs, the 98-prompt set was identical across two repeats. The edited models are not stored here (2.2 and 2.3 GB); `05_derle.py` and `10_derle_itme.py` rebuild them from the unedited model in about a minute. SHA-256 prefixes of the `model.safetensors` we produced: ablation `841b9d6348acf8b6`, push `9b4a15995c49d794`.

## What was changed for release

The scripts originally imported the system instruction, tool schemas and permission function from the assistant's own code. They now read frozen copies in this folder (`talimat.txt`, `araclar.json`, `izin.py`), taken on 9 November 2026 from the same code that produced the results. In `talimat.txt` the one personal line (the user's name) was replaced by a placeholder of the same length, nothing else was edited. Paths under the author's home folder in result files were replaced by `~`. Run logs were removed. The assistant itself (server, Swift app, voice pipeline) is not part of this release.

## How the work was done

Every experiment, from the activation hooks to the final benchmark, was written and run by an LLM coding agent (Claude Fable 5.1 through the Claude Code desktop application) in a single interactive session on the author's laptop, with the author setting goals, approving each step that changed the system, and reading the results. The code has not been independently audited. Issues and reproduction reports are welcome.

## License

MIT, see `LICENSE`. The model weights follow the Qwen license of the base model.
