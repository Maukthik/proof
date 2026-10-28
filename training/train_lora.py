"""
train_lora.py - fine-tune a small model to write proof's case studies (QLoRA, Unsloth).

Runs on a free Kaggle GPU notebook (T4, 16 GB), not on a 6 GB laptop: proof's prompts
are ~10,000 tokens long, and training on that needs more memory than a laptop GPU has.

In a Kaggle notebook (Settings: GPU T4, Internet on), with data.jsonl uploaded as a dataset:

    !pip install unsloth
    !python train_lora.py --data /kaggle/input/<your-dataset>/data.jsonl

It trains LoRA adapters on Llama 3.1 8B Instruct (the model already on your laptop),
only on the assistant's answers (not on the prompts), then exports one GGUF file that
Ollama can run. See training/README.md for the whole loop and how to judge the result.

Not run where it was written (no GPU there). Unsloth and TRL change their APIs now and
then: if a keyword is rejected, the notes next to it say what it was renamed to.
"""

import argparse

# Settings worth changing, and why they are what they are
BASE_MODEL = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"   # same family as your laptop model
MAX_TOKENS = 14000     # longest example (proof dataset prints it) - more costs memory
LORA_RANK = 16         # 8-32 is usual; small data -> small rank
EPOCHS = 2             # few examples: 2-3 passes; more and it memorises them
LEARNING_RATE = 1e-4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="data.jsonl from `proof dataset`")
    parser.add_argument("--out", default="proof-llama", help="Folder for adapters and GGUF")
    args = parser.parse_args()

    # Imported here so `python train_lora.py --help` works without a GPU
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import get_chat_template, train_on_responses_only

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL, max_seq_length=MAX_TOKENS, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=LORA_RANK, lora_alpha=LORA_RANK, lora_dropout=0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",          # trades speed for memory: long prompts
        random_state=0)
    tokenizer = get_chat_template(tokenizer, chat_template="llama-3.1")

    # One training text per example, in Llama 3.1's chat format
    def to_text(batch):
        return {"text": [tokenizer.apply_chat_template(messages, tokenize=False)
                         for messages in batch["messages"]]}
    data = load_dataset("json", data_files=args.data, split="train").map(to_text, batched=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,                  # newer TRL: processing_class=tokenizer
        train_dataset=data,
        args=SFTConfig(
            dataset_text_field="text",
            max_seq_length=MAX_TOKENS,        # newer TRL: max_length=MAX_TOKENS
            per_device_train_batch_size=1,    # one long example at a time ...
            gradient_accumulation_steps=8,    # ... but learn from 8 per step
            num_train_epochs=EPOCHS,
            learning_rate=LEARNING_RATE,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            optim="adamw_8bit",
            logging_steps=5,
            output_dir="outputs",
            seed=0,
            report_to="none"))

    # Learn to write the case study, not to repeat the repo scan in the prompt
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|start_header_id|>user<|end_header_id|>\n\n",
        response_part="<|start_header_id|>assistant<|end_header_id|>\n\n")
    trainer.train()

    model.save_pretrained(f"{args.out}/lora")          # small: the adapters only
    tokenizer.save_pretrained(f"{args.out}/lora")
    # One file for Ollama, same 4-bit size class as the model you run today
    model.save_pretrained_gguf(f"{args.out}/gguf", tokenizer, quantization_method="q4_k_m")
    print(f"Done. Download {args.out}/gguf and follow 'Run it in Ollama' in training/README.md")


if __name__ == "__main__":
    main()
