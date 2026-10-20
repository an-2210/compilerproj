"""Language adapter layer providing compiler/parser invocation and diagnostic extraction.

Supports C, C++, and Python with automatic toolchain discovery and robust fallbacks.
"""

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.data_engine.schemas import (
    Language,
    DiagnosticMessage,
    DiagnosticSeverity,
    ErrorInfo,
)


class CompilationResult:
    """Encapsulates the raw and parsed results of a compiler or parser run."""
    def __init__(
        self,
        success: bool,
        exit_code: int,
        stdout: str,
        stderr: str,
        diagnostics: List[DiagnosticMessage],
        tool_name: str,
        tool_version: Optional[str] = None,
        duration_ms: float = 0.0,
        compiler_available: bool = True,
    ):
        self.success = success
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.diagnostics = diagnostics
        self.tool_name = tool_name
        self.tool_version = tool_version
        self.duration_ms = duration_ms
        self.compiler_available = compiler_available

    def to_error_info(self, category: str, subcategory: Optional[str] = None) -> ErrorInfo:
        return ErrorInfo(
            category=category,
            subcategory=subcategory,
            compiler=self.tool_name,
            compiler_version=self.tool_version,
            exit_code=self.exit_code,
            diagnostics=self.diagnostics,
            raw_output=(self.stderr or self.stdout or "").strip(),
            execution_duration_ms=self.duration_ms,
        )


class LanguageAdapter(ABC):
    """Abstract base class for language adapters."""

    def __init__(self, language: Language):
        self.language = language

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if toolchain/parser is installed and runnable."""
        pass

    @abstractmethod
    def get_tool_version(self) -> Optional[str]:
        """Return the version string of the underlying compiler or parser."""
        pass

    @abstractmethod
    def validate_source(self, source: str) -> bool:
        """Return True if source compiles or parses cleanly without errors."""
        pass

    @abstractmethod
    def compile_or_parse(
        self,
        source: str,
        timeout_seconds: float = 5.0,
        extra_flags: Optional[List[str]] = None,
    ) -> CompilationResult:
        """Run compilation or parsing and return detailed results with diagnostics."""
        pass


def _find_windows_tool(tool_name: str) -> Optional[str]:
    """Search for compiler executable in PATH and standard Windows toolchain dirs."""
    which_path = shutil.which(tool_name)
    if which_path:
        return which_path

    # Common Windows MSYS2 / MinGW search directories
    candidates = [
        Path(f"C:/msys64/ucrt64/bin/{tool_name}.exe"),
        Path(f"C:/msys64/mingw64/bin/{tool_name}.exe"),
        Path(f"C:/mingw64/bin/{tool_name}.exe"),
        Path(f"C:/MinGW/bin/{tool_name}.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve())
    return None


class GccClangBaseAdapter(LanguageAdapter):
    """Base adapter for GCC and Clang family compilers."""

    # Matches gcc/clang diagnostic lines: [drive:]file.c:line:col: severity: message
    DIAG_REGEX = re.compile(
        r"^(?:[a-zA-Z]:[\\/])?(?P<file>[^:\n\r]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|note|fatal error):\s*(?P<msg>.+)$",
        re.MULTILINE | re.IGNORECASE,
    )

    def __init__(self, language: Language, executable_name: str, env_var: str):
        super().__init__(language)
        self.executable_name = executable_name
        self.env_var = env_var
        self._executable_path = self._resolve_executable()
        self._version_cache: Optional[str] = None

    def _resolve_executable(self) -> Optional[str]:
        explicit = os.environ.get(self.env_var)
        if explicit and os.path.exists(explicit):
            return explicit
        return _find_windows_tool(self.executable_name)

    def is_available(self) -> bool:
        return self._executable_path is not None

    def _get_exec_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        if self._executable_path:
            bin_dir = str(Path(self._executable_path).parent)
            current_path = env.get("PATH", "")
            if bin_dir not in current_path:
                env["PATH"] = f"{bin_dir}{os.pathsep}{current_path}"
        return env

    def get_tool_version(self) -> Optional[str]:
        if not self.is_available():
            return None
        if self._version_cache is not None:
            return self._version_cache

        try:
            res = subprocess.run(
                [self._executable_path, "--version"],
                capture_output=True,
                text=True,
                timeout=3.0,
                env=self._get_exec_env(),
            )
            first_line = res.stdout.splitlines()[0] if res.stdout else "unknown"
            self._version_cache = first_line.strip()
            return self._version_cache
        except Exception:
            return "unknown"

    def extract_diagnostics(self, stderr: str, stdout: str) -> List[DiagnosticMessage]:
        diagnostics = []
        combined = (stderr + "\n" + stdout).strip()
        for match in self.DIAG_REGEX.finditer(combined):
            sev_str = match.group("severity").lower()
            if "fatal" in sev_str or "error" in sev_str:
                severity = DiagnosticSeverity.ERROR
            elif "warn" in sev_str:
                severity = DiagnosticSeverity.WARNING
            elif "note" in sev_str:
                severity = DiagnosticSeverity.NOTE
            else:
                severity = DiagnosticSeverity.INFO

            diagnostics.append(
                DiagnosticMessage(
                    # GCC uses typographic quotes in some locales/builds. Keep
                    # raw_text intact, but give downstream rules stable ASCII
                    # punctuation for matching quoted tokens and identifiers.
                    message=match.group("msg").strip().translate(
                        str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})),
                    file=Path(match.group("file")).name,
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    severity=severity,
                    raw_text=match.group(0),
                )
            )

        if not diagnostics and combined:
            # Fallback when regex didn't catch structured output but output is non-empty
            for line in combined.splitlines():
                line_str = line.strip()
                if line_str and not line_str.startswith("In file included from") and not line_str.startswith("compilation terminated"):
                    diagnostics.append(
                        DiagnosticMessage(
                            message=line_str,
                            severity=DiagnosticSeverity.ERROR,
                            raw_text=line_str,
                        )
                    )
                    break
        return diagnostics

    def validate_source(self, source: str) -> bool:
        res = self.compile_or_parse(source)
        return res.success

    def compile_or_parse(
        self,
        source: str,
        timeout_seconds: float = 5.0,
        extra_flags: Optional[List[str]] = None,
    ) -> CompilationResult:
        if not self.is_available():
            return CompilationResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Compiler '{self.executable_name}' is unavailable.",
                diagnostics=[
                    DiagnosticMessage(
                        message=f"Compiler '{self.executable_name}' not found",
                        severity=DiagnosticSeverity.ERROR,
                    )
                ],
                tool_name=self.executable_name,
                tool_version=None,
                compiler_available=False,
            )

        suffix = ".cpp" if self.language == Language.CPP else ".c"
        start_time = time.perf_counter()

        with tempfile.TemporaryDirectory() as tmpdir:
            source_file = Path(tmpdir) / f"input{suffix}"
            source_file.write_text(source, encoding="utf-8")

            cmd = [
                self._executable_path,
                "-fsyntax-only",
                "-Wall",
                str(source_file),
            ]
            if extra_flags:
                cmd.extend(extra_flags)

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    env=self._get_exec_env(),
                    cwd=tmpdir,
                )
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                stdout = proc.stdout[:65536] if proc.stdout else ""
                stderr = proc.stderr[:65536] if proc.stderr else ""
                success = (proc.returncode == 0)
                diagnostics = self.extract_diagnostics(stderr, stdout)

                return CompilationResult(
                    success=success,
                    exit_code=proc.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    diagnostics=diagnostics,
                    tool_name=self.executable_name,
                    tool_version=self.get_tool_version(),
                    duration_ms=duration_ms,
                    compiler_available=True,
                )
            except subprocess.TimeoutExpired:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return CompilationResult(
                    success=False,
                    exit_code=-99,
                    stdout="",
                    stderr=f"Compilation timed out after {timeout_seconds} seconds",
                    diagnostics=[
                        DiagnosticMessage(
                            message=f"Timeout after {timeout_seconds}s",
                            severity=DiagnosticSeverity.ERROR,
                        )
                    ],
                    tool_name=self.executable_name,
                    tool_version=self.get_tool_version(),
                    duration_ms=duration_ms,
                    compiler_available=True,
                )
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000.0
                return CompilationResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    diagnostics=[
                        DiagnosticMessage(
                            message=f"Process invocation error: {e}",
                            severity=DiagnosticSeverity.ERROR,
                        )
                    ],
                    tool_name=self.executable_name,
                    tool_version=self.get_tool_version(),
                    duration_ms=duration_ms,
                    compiler_available=True,
                )


class CAdapter(GccClangBaseAdapter):
    """Adapter for C language using GCC / Clang with pycparser fallback."""

    def __init__(self, executable_name: str = "gcc"):
        super().__init__(Language.C, executable_name, "GCC_PATH")

    def compile_or_parse(
        self,
        source: str,
        timeout_seconds: float = 5.0,
        extra_flags: Optional[List[str]] = None,
    ) -> CompilationResult:
        if self.is_available():
            flags = ["-Werror=implicit-function-declaration"]
            if extra_flags:
                flags.extend(extra_flags)
            return super().compile_or_parse(source, timeout_seconds, flags)
        
        # Pycparser fallback when GCC is not installed
        return self._pycparser_fallback(source)

    def _pycparser_fallback(self, source: str) -> CompilationResult:
        start_time = time.perf_counter()
        try:
            from pycparser import c_parser
            parser = c_parser.CParser()
            parser.parse(source, filename="input.c")
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return CompilationResult(
                success=True,
                exit_code=0,
                stdout="",
                stderr="",
                diagnostics=[],
                tool_name="pycparser",
                tool_version="2.x",
                duration_ms=duration_ms,
                compiler_available=False,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            msg = str(e)
            line = None
            col = None
            match = re.search(r":(\d+):(?:(\d+):)?\s*(.+)", msg)
            if match:
                line = int(match.group(1))
                if match.group(2):
                    col = int(match.group(2))
                msg = match.group(3)

            diag = DiagnosticMessage(
                message=msg,
                line=line,
                column=col,
                severity=DiagnosticSeverity.ERROR,
                raw_text=str(e),
            )
            return CompilationResult(
                success=False,
                exit_code=1,
                stdout="",
                stderr=str(e),
                diagnostics=[diag],
                tool_name="pycparser",
                tool_version="2.x",
                duration_ms=duration_ms,
                compiler_available=False,
            )


class CppAdapter(GccClangBaseAdapter):
    """Adapter for C++ language using G++ / Clang++."""

    def __init__(self, executable_name: str = "g++"):
        super().__init__(Language.CPP, executable_name, "GXX_PATH")


class PythonAdapter(LanguageAdapter):
    """Adapter for Python using the built-in compiler and ast parser."""

    def __init__(self):
        super().__init__(Language.PYTHON)

    def is_available(self) -> bool:
        return True

    def get_tool_version(self) -> Optional[str]:
        return f"Python {sys.version.split()[0]}"

    def validate_source(self, source: str) -> bool:
        res = self.compile_or_parse(source)
        return res.success

    def compile_or_parse(
        self,
        source: str,
        timeout_seconds: float = 5.0,
        extra_flags: Optional[List[str]] = None,
    ) -> CompilationResult:
        start_time = time.perf_counter()
        try:
            # First try ast.parse
            ast.parse(source, filename="<string>")
            # Second try compile to bytecode
            compile(source, "<string>", "exec")
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return CompilationResult(
                success=True,
                exit_code=0,
                stdout="",
                stderr="",
                diagnostics=[],
                tool_name="python_compiler",
                tool_version=self.get_tool_version(),
                duration_ms=duration_ms,
                compiler_available=True,
            )
        except SyntaxError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = e.msg or "SyntaxError"
            line = e.lineno
            col = e.offset
            raw = f"SyntaxError: {err_msg} at line {line}, column {col}"
            diag = DiagnosticMessage(
                message=err_msg,
                file="<string>",
                line=line,
                column=col,
                severity=DiagnosticSeverity.ERROR,
                raw_text=raw,
            )
            return CompilationResult(
                success=False,
                exit_code=1,
                stdout="",
                stderr=raw,
                diagnostics=[diag],
                tool_name="python_compiler",
                tool_version=self.get_tool_version(),
                duration_ms=duration_ms,
                compiler_available=True,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            diag = DiagnosticMessage(
                message=str(e),
                severity=DiagnosticSeverity.ERROR,
                raw_text=str(e),
            )
            return CompilationResult(
                success=False,
                exit_code=1,
                stdout="",
                stderr=str(e),
                diagnostics=[diag],
                tool_name="python_compiler",
                tool_version=self.get_tool_version(),
                duration_ms=duration_ms,
                compiler_available=True,
            )


def get_adapter(language: Language | str) -> LanguageAdapter:
    """Factory function returning the appropriate language adapter."""
    lang_str = language.value if isinstance(language, Language) else str(language).lower()
    if lang_str in ("c",):
        return CAdapter()
    elif lang_str in ("cpp", "c++"):
        return CppAdapter()
    elif lang_str in ("python", "py"):
        return PythonAdapter()
    else:
        raise ValueError(f"Unsupported language: {language}")
