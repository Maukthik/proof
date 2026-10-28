# Fine-tuning a local model for proof

Goal: make the small model on your laptop (Llama 3.1 8B) write case studies that pass
proof's checks on the first try, by training it on good examples.

**Do this only if `proof eval` says it's needed.** The checks and the repair round already
fix a lot. Measure first, train second, then measure again: the eval decides whether the
fine-tuned model replaces the old one.

## How it works

```
1. baseline     proof eval <your repos>              -> problems per case study, today
2. teacher      a big model writes case studies       -> only the ones passing every check
                for ~35 public repos                     are kept (proof does the filtering)
3. dataset      proof dataset                         -> training/data.jsonl
4. train        train_lora.py on a free Kaggle GPU    -> LoRA adapters + one GGUF file
5. install      ollama create proof-llama             -> a new model on your laptop
6. compare      proof eval <your repos> --models <old> proof-llama
```

This is *distillation*: a big model's best work, checked by rules, teaches a small model.
Your own repos are never trained on - they're the test, so the comparison is honest.
Every case study you fix by hand later becomes a top-quality example for the next round.

All commands are for PowerShell in `D:\MyAIProjects\proof`. Quote anything starting
with `@` (PowerShell treats a bare `@` specially).

## 1. Baseline: how good is the model today?

```powershell
py -m proof eval D:\MyAIProjects\doppel https://github.com/Maukthik/client-desk --provider ollama --models llama3.1:8b-instruct-q4_K_M
```

Note the totals line ("N problems in drafts, M after repair, K/2 clean").

## 2. Teacher data: a big model writes case studies for public repos

Any big model works. Free options (they have per-minute limits; proof waits and retries):

- **Groq** (free tier): `llama-3.3-70b-versatile`
- **OpenRouter**: models marked `:free`
- **Anthropic** (paid, best writing): `--provider anthropic`

```powershell
$env:OPENAI_BASE_URL="https://api.groq.com/openai/v1"; $env:OPENAI_API_KEY="<your key>"
py -m proof case "@training/repos.txt" --provider openai --model llama-3.3-70b-versatile --scan-chars 34000 --out teacher_output
```

- `--scan-chars 34000` shows the teacher exactly as much of each repo as your laptop model
  will see, so it learns from examples that fit its context.
- It takes a while (35 repos, each with a possible repair round). If it stops, run the same
  command again: finished repos are skipped.
- Case studies with problems the repair didn't fix are written, but left out of training.
- Add more repos to `training/repos.txt` for more data: 50+ good examples is the minimum
  worth training on, 150+ is better.

## 3. Build the dataset

```powershell
py -m proof dataset --from teacher_output proof_output --exclude doppel client-desk --to training/data.jsonl
```

It prints how many examples it found, where they came from, and the longest one in
tokens (training needs `MAX_TOKENS` in `train_lora.py` above that). `--exclude` keeps your
own repos out, so step 6 tests on projects the model never saw. `data.jsonl` is in
`.gitignore`: it holds other people's code, don't commit it.

## 4. Train on Kaggle (free GPU)

1. kaggle.com -> Create -> New Notebook. Settings: Accelerator **GPU T4**, Internet **on**.
2. Add data: Upload -> New dataset -> `training/data.jsonl`.
3. Upload `training/train_lora.py` the same way (or paste it into a cell as a file).
4. Run:
   ```
   !pip install unsloth
   !python /kaggle/input/<dataset>/train_lora.py --data /kaggle/input/<dataset>/data.jsonl
   ```
5. Expect hours, not minutes, for 100+ long examples (Kaggle gives 30 GPU hours a week).
   The script ends by converting the model to GGUF (that step alone takes a while).
6. Download the `proof-llama/gguf` folder from the notebook's Output.

`train_lora.py` was written without a GPU to run it on. Unsloth and TRL rename things now
and then; if one keyword is rejected, the comment next to it says the new name.

## 5. Install it in Ollama

Put `training/Modelfile` next to the downloaded `.gguf` (fix the file name inside if
needed), then:

```powershell
ollama create proof-llama -f Modelfile
```

## 6. Compare

```powershell
py -m proof eval D:\MyAIProjects\doppel https://github.com/Maukthik/client-desk --provider ollama --models llama3.1:8b-instruct-q4_K_M proof-llama
```

Keep `proof-llama` only if it has fewer problems after repair than the original. If it's
worse, the usual causes are too few examples (it memorised them) or too many epochs.

## 7. Use it

```powershell
$env:PROOF_PROVIDER="ollama"; $env:PROOF_MODEL="proof-llama"
py -m proof case D:\MyAIProjects\doppel --force
```

## Getting better over time

- Every case study you edit by hand is picked up by `proof dataset` as the best kind of
  example ("edited by you"). Fix a few, rebuild the dataset, retrain.
- Clean outputs from `proof eval` runs are collected too.
- Re-run step 6 after every retrain; keep a model only when the numbers improve.
