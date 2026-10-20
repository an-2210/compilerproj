"""Mutation operator registry and base interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type, Set
from src.data_engine.schemas import Language, ErrorCategory


@dataclass
class MutationResult:
    """Outcome of applying a mutation operator to source code."""
    success: bool
    mutated_code: Optional[str] = None
    target_line: Optional[int] = None
    target_column: Optional[int] = None
    operator_id: Optional[str] = None
    operator_version: str = "1.0"
    intended_category: Optional[str] = None
    intended_subcategory: Optional[str] = None
    description: Optional[str] = None
    error_message: Optional[str] = None
    original_token: Optional[str] = None
    mutated_token: Optional[str] = None


class MutationOperator(ABC):
    """Abstract base class for all mutation operators."""

    operator_id: str
    operator_version: str = "1.0"
    supported_languages: List[Language]
    intended_category: str
    intended_subcategory: str
    description: str

    def is_language_supported(self, language: Language | str) -> bool:
        lang_enum = Language(language) if isinstance(language, str) else language
        return lang_enum in self.supported_languages

    @abstractmethod
    def can_apply(self, source: str, language: Language) -> bool:
        """Return True if operator preconditions are met on the source code."""
        pass

    @abstractmethod
    def apply(self, source: str, language: Language, seed: int = 42) -> MutationResult:
        """Apply a single controlled mutation and return the result."""
        pass


class MutationRegistry:
    """Registry maintaining active and available mutation operators."""

    def __init__(self):
        self._operators: Dict[str, MutationOperator] = {}
        self._disabled_ids: Set[str] = set()

    def register(self, operator: MutationOperator) -> None:
        """Register a mutation operator instance."""
        if not operator.operator_id:
            raise ValueError("Operator must declare a non-empty operator_id")
        if operator.operator_id in self._operators:
            raise ValueError(f"Operator '{operator.operator_id}' is already registered")
        self._operators[operator.operator_id] = operator

    def get(self, operator_id: str) -> Optional[MutationOperator]:
        """Retrieve an operator by ID if registered and not disabled."""
        if operator_id in self._disabled_ids:
            return None
        return self._operators.get(operator_id)

    def list_all(self, include_disabled: bool = False) -> List[MutationOperator]:
        """List registered operators."""
        if include_disabled:
            return list(self._operators.values())
        return [op for op_id, op in self._operators.items() if op_id not in self._disabled_ids]

    def get_applicable(self, source: str, language: Language) -> List[MutationOperator]:
        """Return operators that support the language and meet preconditions."""
        applicable = []
        for op in self.list_all(include_disabled=False):
            if op.is_language_supported(language):
                try:
                    if op.can_apply(source, language):
                        applicable.append(op)
                except Exception:
                    continue
        return applicable

    def disable(self, operator_id: str) -> None:
        """Disable an operator by ID."""
        self._disabled_ids.add(operator_id)

    def enable(self, operator_id: str) -> None:
        """Re-enable a previously disabled operator."""
        self._disabled_ids.discard(operator_id)


# Global registry instance
default_registry = MutationRegistry()
