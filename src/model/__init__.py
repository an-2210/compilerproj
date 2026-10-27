"""P3 ML Engineer Package: AI-Based Compiler Error Repair Layer.

Provides:
- Data contracts: MLRepairCandidate, RepairFeedback, FewShotExample, StructuredModelOutput.
- Prompt builders: build_zero_shot_prompt, build_few_shot_prompt, build_feedback_prompt.
- Providers: ModelProvider, MockModelProvider, HostedLLMProvider.
- Repair model & candidate generator: analyze_and_repair, RepairModel, compute_unified_diff.
- Feedback loop: feedback_retry_loop, create_feedback_from_detection.
"""

from src.model.schemas import (
    FewShotExample,
    MLRepairCandidate,
    ModelOutputParseError,
    ProviderUnavailableError,
    RepairCandidate,
    RepairCategory,
    RepairFeedback,
    RepairModelError,
    StructuredModelOutput,
    ExcessiveEditError,
    UnchangedCodeError,
)
from src.model.prompts import (
    build_feedback_prompt,
    build_few_shot_prompt,
    build_zero_shot_prompt,
)
from src.model.repair_model import (
    HostedLLMProvider,
    MockModelProvider,
    ModelProvider,
    OllamaProvider,
    RepairModel,
    get_provider,
    parse_model_output,
)
from src.model.candidate_generator import (
    analyze_and_repair,
    compute_edit_distance,
    compute_edit_metrics,
    compute_unified_diff,
    create_candidate,
    is_excessive_edit,
    normalize_code,
)
from src.model.feedback import (
    create_feedback_from_detection,
    feedback_retry_loop,
)
from src.model.lora_finetune import (
    LoRATrainingConfig,
    check_training_prerequisites,
    run_lora_finetune,
)

__all__ = [
    # Schemas
    "MLRepairCandidate",
    "RepairCandidate",
    "StructuredModelOutput",
    "FewShotExample",
    "RepairFeedback",
    "RepairCategory",
    "RepairModelError",
    "ModelOutputParseError",
    "ProviderUnavailableError",
    "ExcessiveEditError",
    "UnchangedCodeError",
    # Prompts
    "build_zero_shot_prompt",
    "build_few_shot_prompt",
    "build_feedback_prompt",
    # Providers and Model
    "ModelProvider",
    "MockModelProvider",
    "HostedLLMProvider",
    "OllamaProvider",
    "get_provider",
    "RepairModel",
    "parse_model_output",
    # Generator API
    "analyze_and_repair",
    "create_candidate",
    "compute_unified_diff",
    "compute_edit_metrics",
    "compute_edit_distance",
    "normalize_code",
    "is_excessive_edit",
    # Feedback
    "feedback_retry_loop",
    "create_feedback_from_detection",
    # LoRA
    "LoRATrainingConfig",
    "check_training_prerequisites",
    "run_lora_finetune",
]
