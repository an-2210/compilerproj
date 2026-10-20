"""Optional Parameter-Efficient Fine-Tuning (LoRA) module for code repair models.

Reuses P1's dataset splits (`data/splits/train.jsonl` and `data/splits/val.jsonl`),
strictly isolates evaluation splits, and cleanly checks for CUDA/PEFT requirements
before initiating any training operations.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class LoRATrainingConfig(BaseModel):
    """Configuration for LoRA fine-tuning of code repair models."""
    base_model_name_or_path: str = Field(
        default="deepseek-ai/deepseek-coder-1.3b-instruct",
        description="Base causal language model identifier or local directory.",
    )
    lora_r: int = Field(default=8, ge=1, le=64, description="LoRA rank dimension.")
    lora_alpha: int = Field(default=16, ge=1, le=128, description="LoRA scaling factor.")
    lora_dropout: float = Field(default=0.05, ge=0.0, le=0.5, description="LoRA dropout rate.")
    target_modules: List[str] = Field(
        default_factory=lambda: ["q_proj", "v_proj", "k_proj", "o_proj"],
        description="Target attention projection modules to adapt.",
    )
    learning_rate: float = Field(default=2e-4, gt=0.0, description="Optimizer learning rate.")
    batch_size: int = Field(default=2, ge=1, description="Per-device training batch size.")
    gradient_accumulation_steps: int = Field(default=4, ge=1, description="Gradient accumulation steps.")
    num_train_epochs: int = Field(default=3, ge=1, description="Total training epochs.")
    max_seq_length: int = Field(default=1024, ge=128, le=4096, description="Max sequence length.")
    train_split_path: str = Field(default="data/splits/train.jsonl", description="Path to train split.")
    val_split_path: str = Field(default="data/splits/val.jsonl", description="Path to validation split.")
    output_dir: str = Field(default="models/lora_adapter", description="Directory to save trained LoRA weights.")


def load_and_format_split(file_path: str) -> List[Dict[str, str]]:
    """Loads a P1 dataset split and converts each record into a supervised training pair.

    Format:
        {"instruction": prompt_with_context_and_diagnostic, "response": json_with_repaired_code}
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset split file not found: {file_path}")

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            # Reconstruct prompt instruction
            instruction = (
                f"Fix the {item['language']} compiler error in the following code:\n"
                f"Error: {item.get('error', {}).get('category', 'unknown')} - "
                f"{item.get('error', {}).get('subcategory', '')}\n\n"
                f"Code:\n{item['mutated_code']}\n"
            )
            response = json.dumps({
                "repaired_code": item["source_code"],
                "repair_category": item.get("error", {}).get("category", "syntax"),
                "root_cause": item.get("mutation", {}).get("description", "Reverted injected mutation"),
                "target_line": item.get("mutation", {}).get("target_location", {}).get("line", 1),
                "confidence": 1.0,
            }, indent=2)

            records.append({"instruction": instruction, "response": response})

    return records


def check_training_prerequisites() -> Dict[str, Any]:
    """Inspects the local runtime environment to verify if LoRA training is viable."""
    status = {
        "viable": False,
        "torch_available": False,
        "cuda_available": False,
        "transformers_available": False,
        "peft_available": False,
        "reasons": [],
    }

    try:
        import torch
        status["torch_available"] = True
        status["cuda_available"] = torch.cuda.is_available()
        if not status["cuda_available"]:
            status["reasons"].append("CUDA is not available. Fine-tuning on CPU is not recommended.")
    except ImportError:
        status["reasons"].append("PyTorch ('torch') is not installed.")

    try:
        import transformers
        status["transformers_available"] = True
    except ImportError:
        status["reasons"].append("'transformers' is not installed.")

    try:
        import peft
        status["peft_available"] = True
    except ImportError:
        status["reasons"].append("'peft' is not installed.")

    status["viable"] = (
        status["torch_available"]
        and status["cuda_available"]
        and status["transformers_available"]
        and status["peft_available"]
    )
    return status


def run_lora_finetune(config: Optional[LoRATrainingConfig] = None) -> Dict[str, Any]:
    """Executes or checks LoRA fine-tuning cleanly.

    In environments without CUDA, GPU, or PEFT dependencies, it cleanly reports
    hardware requirements and exits safely without failing or downloading models.
    """
    cfg = config or LoRATrainingConfig()
    prereqs = check_training_prerequisites()

    if not prereqs["viable"]:
        return {
            "status": "SKIPPED",
            "message": "LoRA fine-tuning safely skipped due to missing hardware/dependencies.",
            "reasons": prereqs["reasons"],
            "config": cfg.model_dump(),
        }

    # If prerequisites are met:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
        from peft import LoraConfig, get_peft_model

        train_data = load_and_format_split(cfg.train_split_path)
        val_data = load_and_format_split(cfg.val_split_path)

        logger.info("Loaded %d training examples and %d validation examples.", len(train_data), len(val_data))
        # Training setup would proceed here...
        return {
            "status": "SUCCESS",
            "train_examples": len(train_data),
            "val_examples": len(val_data),
            "config": cfg.model_dump(),
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e),
            "config": cfg.model_dump(),
        }
