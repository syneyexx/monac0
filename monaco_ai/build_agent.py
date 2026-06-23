from __future__ import annotations

import difflib
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .llm import LMStudioClient
from .utils import sha256_text, truncate_middle

TEXT_EXTENSIONS = {
    ".py", ".json", ".md", ".txt", ".bat", ".ps1", ".sh", ".yml", ".yaml", ".toml",
    ".ini", ".cfg", ".html", ".css", ".js", ".ts", ".sql", ".csv", ".xml",
}
EXCLUDE_NAMES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "venv", ".venv",
    "env", ".env", "monaco_memory.db", "monaco_memory.db-shm", "monaco_memory.db-wal",
}
MAX_FILE_CHARS = 26000
MAX_CONTEXT_CHARS = 85000
SMALL_CONTEXT_TOTAL_CHARS = 32000
SMALL_CONTEXT_FILE_CHARS = 11000
SMALL_CONTEXT_FILE_LIMIT = 5



@dataclass(slots=True)
class BuildAgentResult:
    ok: bool
    workspace: Path
    source_root: Path
    output_zip: Path | None = None
    plan: str = ""
    summary: str = ""
    changed_files: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    diffs: dict[str, str] = field(default_factory=dict)
    test_report: str = ""
    error: str | None = None
    export_verified: bool = False
    rollback_available: bool = False

    def report(self) -> str:
        lines = [
            f"OK: {self.ok}",
            f"Workspace: {self.workspace}",
            f"Source root: {self.source_root}",
            f"Output zip: {self.output_zip or '-'}",
            f"Export verified: {self.export_verified}",
            f"Rollback available: {self.rollback_available}",
            "",
            "PLAN",
            self.plan or "-",
            "",
            "SUMMARY",
            self.summary or "-",
            "",
            "CHANGED FILES",
            *(self.changed_files or ["-"]),
            "",
            "CHECKS",
            *(self.checks or ["-"]),
        ]
        if self.test_report:
            lines.extend(["", "AUTO TEST REPORT", self.test_report])
        if self.error:
            lines.extend(["", "ERROR", self.error])
        if self.logs:
            lines.extend(["", "LOGS", *self.logs[-80:]])
        return "\n".join(lines)

    def diff_text(self, max_chars: int = 80000) -> str:
        if not self.diffs:
            return "No diff available."
        chunks: list[str] = []
        for path, diff in self.diffs.items():
            chunks.append(f"### DIFF: {path}\n{diff}")
        return truncate_middle("\n\n".join(chunks), max_chars)


class BuildAgent:
    """Safe source-patching agent.

    Guarantees:
    - Never edits the real project folder directly.
    - Never exports .env, SQLite DBs, caches or bytecode.
    - Never reports success unless real file changes were written and verified.
    - Keeps a rollback snapshot in every workspace.
    """

    def __init__(self, project_root: Path, llm: LMStudioClient, log: Callable[[str], None] | None = None):
        self.project_root = Path(project_root)
        self.llm = llm
        self.log = log or (lambda msg: None)
        self.workspace_root = self.project_root / "data" / "build_agent_workspaces"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.last_preview_process: subprocess.Popen | None = None

    def run(self, source: str | Path, instruction: str, manual_targets: list[str] | None = None) -> BuildAgentResult:
        instruction = (instruction or "").strip()
        if not instruction:
            raise ValueError("Geen opdracht ingevuld.")
        source_path = Path(str(source or "")).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"Source bestaat niet: {source_path}")
        job_id = time.strftime("%Y%m%d_%H%M%S") + "_" + sha256_text(str(source_path) + instruction)[:8]
        workspace = self.workspace_root / f"job_{job_id}"
        src_root = workspace / "source"
        rollback_root = workspace / "rollback_original"
        workspace.mkdir(parents=True, exist_ok=True)
        logs: list[str] = []

        def log(msg: str) -> None:
            logs.append(msg)
            self.log(msg)

        result = BuildAgentResult(ok=False, workspace=workspace, source_root=src_root, logs=logs)
        try:
            log("Creating safe workspace...")
            self._prepare_source(source_path, src_root)
            self._copytree_safe(src_root, rollback_root)
            result.rollback_available = True
            before_hashes = self._hash_text_files(src_root)
            files = self._scan_text_files(src_root)
            log(f"Scanned {len(files)} text/code files.")
            selected = self._resolve_target_files(src_root, files, instruction, manual_targets)
            log(f"Selected {len(selected)} relevant files for patch context.")
            if manual_targets:
                log("Manual File Target Mode actief: alleen opgegeven files worden naar de LLM gestuurd/toegestaan.")
            context = self._build_context(src_root, selected)
            plan = self._make_plan(instruction, files, context)
            result.plan = plan
            changes, change_notes = self._ask_for_changes_with_recovery(
                instruction=instruction,
                plan=plan,
                root=src_root,
                all_files=files,
                selected=selected,
                full_context=context,
                manual_targets=manual_targets or [],
                logs=logs,
            )
            if change_notes:
                result.checks.extend(change_notes)
            if not changes:
                result.error = (
                    "LLM gaf geen gestructureerde file-wijzigingen terug. Geen export gemaakt, want No Fake Success is actief.\n\n"
                    "Tip: gebruik Manual File Target Mode met 1-5 files, maak de opdracht kleiner, verhoog LM Studio context length, "
                    "of kies een coding model met grotere context/strakkere JSON-output."
                )
                result.summary = "No real source changes were produced."
                result.checks.extend(["FAIL no structured file changes returned; export blocked."])
                return result
            changed = self._apply_changes(src_root, changes)
            after_hashes = self._hash_text_files(src_root)
            changed = self._changed_files_from_hashes(before_hashes, after_hashes)
            result.changed_files = changed
            if not changed:
                result.error = "Er zijn geen echte file-wijzigingen gevonden na patchen. Export geblokkeerd."
                result.summary = "No files changed. Build Agent refused fake success."
                result.checks = ["FAIL no file hashes changed; export blocked."]
                return result
            result.diffs = self._generate_diffs(rollback_root, src_root, changed)
            result.summary = self._summarize_changes(instruction, plan, changed)
            preflight_checks = list(result.checks)
            result.checks = preflight_checks + self._run_checks(src_root)
            result.test_report = self._create_test_report(src_root, changed, result.checks)
            if any(line.startswith("FAIL") for line in result.checks):
                result.error = "Checks failed. Export is still created only if explicitly requested via export_final_zip; auto-export blocked."
                return result
            out_zip = self.export_final_zip(src_root, workspace / f"M0N4C0_PATCHED_{job_id}.zip", changed)
            result.output_zip = out_zip
            result.export_verified = self._verify_export(out_zip, changed)
            result.ok = bool(changed and result.export_verified and not any(line.startswith("FAIL") for line in result.checks))
            if not result.ok:
                result.error = result.error or "Export verification failed."
            return result
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            log(result.error)
            return result

    def analyze_only(self, source: str | Path, instruction: str, manual_targets: list[str] | None = None) -> BuildAgentResult:
        source_path = Path(str(source or "")).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"Source bestaat niet: {source_path}")
        job_id = time.strftime("%Y%m%d_%H%M%S") + "_analysis_" + sha256_text(str(source_path))[:8]
        workspace = self.workspace_root / f"job_{job_id}"
        src_root = workspace / "source"
        logs: list[str] = []
        result = BuildAgentResult(ok=True, workspace=workspace, source_root=src_root, logs=logs)
        self._prepare_source(source_path, src_root)
        files = self._scan_text_files(src_root)
        selected = self._resolve_target_files(src_root, files, instruction, manual_targets)
        context = self._build_context(src_root, selected)
        result.plan = self._make_plan(instruction, files, context)
        result.summary = f"Analyzed {len(files)} files. Selected {len(selected)} likely relevant files. No files changed."
        result.changed_files = []
        result.checks = ["OK analysis only; no files changed."]
        result.test_report = self._create_test_report(src_root, [], result.checks)
        return result

    def run_checks_only(self, source_root: str | Path) -> list[str]:
        return self._run_checks(Path(source_root))

    def export_final_zip(self, source_root: str | Path, output_zip: str | Path | None = None, expected_changed_files: list[str] | None = None) -> Path:
        root = Path(source_root)
        if output_zip is None:
            output_zip = root.parent / f"M0N4C0_EXPORT_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        out = self._create_export_zip(root, Path(output_zip))
        if expected_changed_files and not self._verify_export(out, expected_changed_files):
            raise RuntimeError("Export zip verification failed: changed files missing from zip.")
        return out

    def rollback_workspace(self, workspace: str | Path) -> tuple[bool, str]:
        workspace = Path(workspace)
        source = workspace / "source"
        backup = workspace / "rollback_original"
        if not backup.exists():
            return False, "Geen rollback snapshot gevonden."
        if source.exists():
            shutil.rmtree(source)
        self._copytree_safe(backup, source)
        return True, f"Workspace hersteld naar originele snapshot: {source}"

    def run_preview(self, source_root: str | Path) -> subprocess.Popen:
        root = Path(source_root)
        command = self._preview_command(root)
        if not command:
            raise RuntimeError("Geen preview startpunt gevonden (START_GUI.bat, run_m0n4c0.py of main.py).")
        if sys.platform.startswith("win"):
            if command[0].lower().endswith(".bat"):
                return subprocess.Popen(["cmd", "/k", str(root / command[0])], cwd=str(root), creationflags=subprocess.CREATE_NEW_CONSOLE)  # type: ignore[attr-defined]
            return subprocess.Popen(["cmd", "/k", *command], cwd=str(root), creationflags=subprocess.CREATE_NEW_CONSOLE)  # type: ignore[attr-defined]
        # Linux/macOS: run in normal subprocess; GUI can open workspace/logs. Real terminal launch varies per desktop.
        return subprocess.Popen(command, cwd=str(root))

    def stop_preview(self, proc: subprocess.Popen | None) -> bool:
        if proc is None or proc.poll() is not None:
            return False
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        return True

    def _preview_command(self, root: Path) -> list[str] | None:
        if (root / "START_GUI.bat").exists() and sys.platform.startswith("win"):
            return ["START_GUI.bat"]
        if (root / "run_m0n4c0.py").exists():
            return [sys.executable, "run_m0n4c0.py", "--gui"]
        if (root / "main.py").exists():
            return [sys.executable, "main.py", "--gui"]
        return None

    def _prepare_source(self, source_path: Path, dest: Path) -> None:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        if source_path.is_file() and source_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(source_path) as zf:
                self._safe_extract(zf, dest)
            self._flatten_single_top_folder(dest)
        elif source_path.is_dir():
            self._copytree_safe(source_path, dest)
        else:
            raise ValueError("Gebruik een .zip-bestand of projectmap.")

    def _flatten_single_top_folder(self, dest: Path) -> None:
        children = [p for p in dest.iterdir() if p.name not in {"__MACOSX"}]
        if len(children) == 1 and children[0].is_dir():
            tmp = dest.parent / (dest.name + "_flat")
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)
            for item in children[0].iterdir():
                shutil.move(str(item), str(tmp / item.name))
            shutil.rmtree(dest)
            shutil.move(str(tmp), str(dest))

    def _safe_extract(self, zf: zipfile.ZipFile, dest: Path) -> None:
        max_members = 10000
        max_total = 512 * 1024 * 1024
        total = 0
        members = zf.infolist()
        if len(members) > max_members:
            raise ValueError(f"Zip heeft te veel bestanden ({len(members)} > {max_members}).")
        for member in members:
            name = member.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            parts = Path(name).parts
            if any(part in EXCLUDE_NAMES for part in parts):
                continue
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"Zip-slip pad geblokkeerd: {name}")
            total += member.file_size
            if total > max_total:
                raise ValueError("Zip is te groot voor veilige build-agent workspace.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    def _copytree_safe(self, source: Path, dest: Path) -> None:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(source):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if d not in EXCLUDE_NAMES]
            rel = root_path.relative_to(source)
            for file_name in files:
                if file_name in EXCLUDE_NAMES or file_name.endswith((".db", ".db-wal", ".db-shm", ".pyc")):
                    continue
                src = root_path / file_name
                dst = dest / rel / file_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.stat().st_size > 25 * 1024 * 1024:
                    continue
                shutil.copy2(src, dst)

    def _scan_text_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXCLUDE_NAMES for part in path.parts):
                continue
            if path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size <= 768 * 1024:
                files.append(path.relative_to(root))
        return sorted(files, key=lambda p: (0 if p.name in {"main.py", "gui.py", "README.md"} else 1, str(p).lower()))

    def _hash_text_files(self, root: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for rel in self._scan_text_files(root):
            p = root / rel
            try:
                data = p.read_bytes()
            except Exception:
                continue
            hashes[rel.as_posix()] = hashlib.sha256(data).hexdigest()
        return hashes

    def _changed_files_from_hashes(self, before: dict[str, str], after: dict[str, str]) -> list[str]:
        changed = sorted([p for p, h in after.items() if before.get(p) != h])
        removed = sorted([p for p in before.keys() if p not in after])
        return changed + [f"DELETED:{p}" for p in removed]

    def _normalize_manual_targets(self, manual_targets: list[str] | None) -> list[str]:
        targets: list[str] = []
        for raw in manual_targets or []:
            for piece in re.split(r"[,;\n]+", str(raw)):
                clean = piece.strip().strip('"').strip("'").replace("\\", "/")
                if clean and clean not in targets:
                    targets.append(clean)
        return targets

    def _resolve_target_files(self, root: Path, files: list[Path], instruction: str, manual_targets: list[str] | None = None) -> list[Path]:
        """Return files allowed for LLM context.

        Manual File Target Mode is intentionally strict: if the user enters
        paths, the Build Agent will only send those files to the model and only
        accept replacements for those paths. This prevents context explosions
        and accidental wide edits.
        """
        targets = self._normalize_manual_targets(manual_targets)
        if targets:
            known = {p.as_posix().lower(): p for p in files}
            resolved: list[Path] = []
            for target in targets:
                key = target.lower().lstrip("./")
                if key in known:
                    resolved.append(known[key])
                    continue
                # Allow loose filename match for convenience, but only if it is unique.
                matches = [p for p in files if p.name.lower() == Path(key).name.lower() or key in p.as_posix().lower()]
                if len(matches) == 1:
                    resolved.append(matches[0])
            return resolved[:12]
        return self._select_relevant_files(files, instruction, limit=18)

    def _select_relevant_files(self, files: list[Path], instruction: str, limit: int = 18) -> list[Path]:
        lower = instruction.lower()
        terms = set(re.findall(r"[a-zA-Z0-9_\.\-]{3,}", lower))
        scored: list[tuple[int, Path]] = []
        for rel in files:
            s = str(rel).lower()
            score = 0
            if rel.name in {"main.py", "gui.py", "commands.py", "db.py", "llm.py", "build_agent.py"}:
                score += 3
            for term in terms:
                if term in s:
                    score += 4
            rules = [
                (["gui", "pagina", "button", "sidebar", "tkinter"], ["gui", "main.py"]),
                (["telegram", "bot"], ["telegram"]),
                (["database", "sqlite", "sql", "db"], ["db.py", "database"]),
                (["llm", "model", "prompt"], ["llm", "model"]),
                (["build", "agent", "source", "patch", "diff"], ["build_agent", "gui.py"]),
                (["tools", "dependency", "plugin", "safe mode"], ["tools", "config", "gui.py"]),
            ]
            for needles, names in rules:
                if any(key in lower for key in needles) and any(part in s for part in names):
                    score += 8
            if score:
                scored.append((score, rel))
        scored.sort(key=lambda x: (-x[0], str(x[1])))
        selected = [p for _, p in scored[:limit]]
        if not selected:
            selected = files[:min(limit, len(files))]
        return selected

    def _build_context(self, root: Path, selected: list[Path]) -> str:
        chunks: list[str] = []
        for rel in selected:
            path = root / rel
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            text = truncate_middle(text, MAX_FILE_CHARS)
            chunks.append(f"### FILE: {rel.as_posix()}\n{text}")
        return truncate_middle("\n\n".join(chunks), MAX_CONTEXT_CHARS)

    def _safe_llm_chat(self, system: str, user: str, context: str = ""):
        old_timeout = getattr(self.llm.settings, "lmstudio_timeout", 120)
        old_role = getattr(self.llm.settings, "llm_forced_model_role", "auto")
        try:
            self.llm.settings.lmstudio_timeout = min(int(old_timeout or 120), 60)
            self.llm.settings.llm_forced_model_role = "code"
            return self.llm.safe_chat(system, user, context, attempts=2)
        finally:
            self.llm.settings.lmstudio_timeout = old_timeout
            self.llm.settings.llm_forced_model_role = old_role

    def _make_plan(self, instruction: str, files: list[Path], context: str) -> str:
        file_list = "\n".join(f"- {p.as_posix()}" for p in files[:260])
        prompt = (
            "Maak een concreet technisch plan voor deze codewijziging. "
            "Noem files, risico's, checks en hoe echte wijzigingen geverifieerd worden. Antwoord Nederlands."
        )
        result = self._safe_llm_chat(prompt, instruction, f"PROJECT FILES:\n{file_list}\n\nRELEVANT CONTEXT:\n{context}")
        if result.text and not result.error:
            return result.text
        return (
            "LLM-plan niet beschikbaar. Heuristisch plan:\n"
            "1. Werk uitsluitend in de tijdelijke workspace.\n"
            "2. Pas alleen relevante tekst/codebestanden aan.\n"
            "3. Draai py_compile/JSON/export checks.\n"
            "4. Exporteer zip zonder database, .env en caches.\n"
            f"LLM melding: {result.error or 'geen antwoord'}"
        )

    def _ask_for_changes_with_recovery(
        self,
        *,
        instruction: str,
        plan: str,
        root: Path,
        all_files: list[Path],
        selected: list[Path],
        full_context: str,
        manual_targets: list[str],
        logs: list[str],
    ) -> tuple[list[dict[str, str]], list[str]]:
        notes: list[str] = []
        allowed = {p.as_posix() for p in selected}
        changes, error = self._ask_for_changes_once(instruction, plan, full_context, allowed_paths=allowed or None)
        if changes:
            notes.append("OK LLM returned structured file changes in normal-context mode.")
            return changes, notes
        if error:
            notes.append(f"WARN normal-context patch failed: {error}")
        if not self._is_context_overflow_error(error or "") and manual_targets:
            # Manual mode should already be small. If it still failed, don't let
            # a second broad retry modify unrelated files.
            return [], notes

        # Context-overflow or no structured output: use smaller targeted retry.
        logs.append("Switching to small-context patch mode.")
        notes.append("WARN small-context retry activated: using filenames/summaries + 3-5 focused files.")
        small_files = self._choose_small_context_files(root, all_files, instruction, plan, selected, manual_targets)
        if not small_files:
            return [], notes
        allowed_small = {p.as_posix() for p in small_files}
        small_context = self._build_snippet_context(root, small_files, instruction)
        changes, error = self._ask_for_changes_once(instruction, plan, small_context, allowed_paths=allowed_small)
        if changes:
            notes.append(f"OK LLM returned structured changes in small-context mode ({len(small_files)} files).")
            return changes, notes
        if error:
            notes.append(f"FAIL small-context patch failed: {error}")
        return [], notes

    def _ask_for_changes_once(
        self,
        instruction: str,
        plan: str,
        context: str,
        *,
        allowed_paths: set[str] | None = None,
    ) -> tuple[list[dict[str, str]], str | None]:
        system = (
            "Je bent een senior Python/Tkinter build agent. Geef ALLEEN geldig JSON terug, geen markdown. "
            "Schema: {\"summary\": str, \"files\": [{\"path\": \"relative/path\", \"content\": \"complete file content\"}]}. "
            "Geef alleen complete file replacements terug voor files die je zeker correct kunt herschrijven. Geen database/.env. "
            "Als je niets kunt wijzigen, geef {\"summary\":\"no changes\",\"files\":[]} terug."
        )
        allowed_text = ""
        if allowed_paths:
            allowed_text = "\n\nTOEGESTANE FILES — wijzig uitsluitend deze paden:\n" + "\n".join(f"- {p}" for p in sorted(allowed_paths))
        user = (
            f"OPDRACHT:\n{instruction}\n\nPLAN:\n{plan}{allowed_text}\n\n"
            "Maak de wijziging nu. Return complete replacement content voor gewijzigde files. "
            "Geen uitleg buiten JSON."
        )
        result = self._safe_llm_chat(system, user, context)
        if result.error and self._is_context_overflow_error(result.error):
            return [], result.error
        if not result.text:
            return [], result.error or "geen tekst van LLM"
        data = self._parse_json_object(result.text)
        files = data.get("files") if isinstance(data, dict) else None
        if not isinstance(files, list):
            return [], "LLM antwoord bevatte geen geldig JSON files-array"
        clean: list[dict[str, str]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip().replace("\\", "/")
            content = item.get("content")
            if not path or content is None:
                continue
            if allowed_paths and path not in allowed_paths:
                # Never allow the LLM to wander outside the selected/manual files.
                continue
            clean.append({"path": path, "content": str(content)})
        return clean, None if clean else "LLM gaf geen toepasbare wijzigingen voor toegestane files"

    def _is_context_overflow_error(self, error: str) -> bool:
        low = (error or "").lower()
        return any(token in low for token in ["context size", "context length", "context window", "maximum context", "too many tokens", "exceeded"])

    def _choose_small_context_files(
        self,
        root: Path,
        all_files: list[Path],
        instruction: str,
        plan: str,
        selected: list[Path],
        manual_targets: list[str],
    ) -> list[Path]:
        if manual_targets:
            return self._resolve_target_files(root, all_files, instruction, manual_targets)[:SMALL_CONTEXT_FILE_LIMIT]

        # First ask the model using only a compact file list. If that fails,
        # fall back to deterministic heuristic scoring.
        file_summary = self._build_file_summary(root, all_files, instruction, max_files=260)
        system = (
            "Je kiest alleen relevante bestanden voor een codewijziging. "
            "Geef ALLEEN JSON terug: {\"files\":[\"relative/path.py\"]}. "
            f"Kies maximaal {SMALL_CONTEXT_FILE_LIMIT} bestanden."
        )
        user = f"OPDRACHT:\n{instruction}\n\nPLAN:\n{plan}\n\nKies de kleinste set bestanden die nodig is."
        result = self._safe_llm_chat(system, user, file_summary)
        picked: list[Path] = []
        if result.text and not result.error:
            data = self._parse_json_object(result.text)
            raw_files = data.get("files") if isinstance(data, dict) else []
            known = {p.as_posix(): p for p in all_files}
            if isinstance(raw_files, list):
                for raw in raw_files:
                    key = str(raw).strip().replace("\\", "/")
                    if key in known and known[key] not in picked:
                        picked.append(known[key])
                    if len(picked) >= SMALL_CONTEXT_FILE_LIMIT:
                        break
        if picked:
            return picked
        # Heuristic fallback: reuse selected files but cut aggressively.
        return (selected or self._select_relevant_files(all_files, instruction, limit=SMALL_CONTEXT_FILE_LIMIT))[:SMALL_CONTEXT_FILE_LIMIT]

    def _build_file_summary(self, root: Path, files: list[Path], instruction: str, max_files: int = 260) -> str:
        lines = ["PROJECT FILE SUMMARY"]
        lower_instruction = instruction.lower()
        terms = set(re.findall(r"[a-zA-Z0-9_\.\-]{4,}", lower_instruction))
        for rel in files[:max_files]:
            path = root / rel
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:5000]
            except Exception:
                text = ""
            matches = [t for t in terms if t in rel.as_posix().lower() or t in text.lower()]
            size = path.stat().st_size if path.exists() else 0
            hints = []
            if rel.suffix.lower() == ".py":
                hints.extend(re.findall(r"(?m)^\s*(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", text)[:8])
            lines.append(f"- {rel.as_posix()} | {size} bytes | matches={','.join(matches[:8]) or '-'} | symbols={','.join(hints) or '-'}")
        return truncate_middle("\n".join(lines), 28000)

    def _build_snippet_context(self, root: Path, selected: list[Path], instruction: str) -> str:
        chunks: list[str] = []
        used = 0
        for rel in selected[:SMALL_CONTEXT_FILE_LIMIT]:
            path = root / rel
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            snippet = self._extract_relevant_snippet(text, instruction, SMALL_CONTEXT_FILE_CHARS)
            block = f"### FILE: {rel.as_posix()}\n{snippet}"
            if used + len(block) > SMALL_CONTEXT_TOTAL_CHARS:
                remaining = SMALL_CONTEXT_TOTAL_CHARS - used
                if remaining <= 1200:
                    break
                block = truncate_middle(block, remaining)
            chunks.append(block)
            used += len(block)
        return "\n\n".join(chunks)

    def _extract_relevant_snippet(self, text: str, instruction: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        lines = text.splitlines()
        low_terms = [t.lower() for t in re.findall(r"[a-zA-Z0-9_\.\-]{4,}", instruction)][:60]
        hit_indexes: list[int] = []
        for idx, line in enumerate(lines):
            low = line.lower()
            if any(t in low for t in low_terms):
                hit_indexes.append(idx)
        if not hit_indexes:
            # Include imports/top-level definitions and middle/end context.
            top = "\n".join(lines[:140])
            return truncate_middle(top + "\n\n" + text, max_chars)
        spans: list[tuple[int, int]] = []
        radius = 70
        for idx in hit_indexes[:12]:
            spans.append((max(0, idx - radius), min(len(lines), idx + radius)))
        spans.sort()
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if not merged or start > merged[-1][1] + 8:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        snippets: list[str] = []
        for start, end in merged:
            snippets.append(f"# --- snippet lines {start+1}-{end} ---\n" + "\n".join(lines[start:end]))
        return truncate_middle("\n\n".join(snippets), max_chars)

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
        if fenced:
            text = fenced.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _apply_changes(self, root: Path, changes: list[dict[str, str]]) -> list[str]:
        changed: list[str] = []
        for item in changes:
            rel_raw = item["path"].strip().replace("\\", "/")
            rel = Path(rel_raw)
            if rel.is_absolute() or ".." in rel.parts or any(part in EXCLUDE_NAMES for part in rel.parts):
                continue
            target = (root / rel).resolve()
            if not str(target).startswith(str(root.resolve())):
                continue
            content = item["content"]
            old = target.read_text(encoding="utf-8", errors="replace") if target.exists() and target.suffix.lower() in TEXT_EXTENSIONS else None
            if old == content:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            changed.append(rel.as_posix())
        return changed

    def _generate_diffs(self, before_root: Path, after_root: Path, changed: list[str]) -> dict[str, str]:
        diffs: dict[str, str] = {}
        for rel in changed:
            if rel.startswith("DELETED:"):
                clean_rel = rel.split(":", 1)[1]
            else:
                clean_rel = rel
            before = before_root / clean_rel
            after = after_root / clean_rel
            before_text = before.read_text(encoding="utf-8", errors="replace").splitlines() if before.exists() else []
            after_text = after.read_text(encoding="utf-8", errors="replace").splitlines() if after.exists() else []
            diff = "\n".join(difflib.unified_diff(before_text, after_text, fromfile=f"before/{clean_rel}", tofile=f"after/{clean_rel}", lineterm=""))
            diffs[rel] = truncate_middle(diff or "(binary/empty diff)", 24000)
        return diffs

    def _summarize_changes(self, instruction: str, plan: str, changed: list[str]) -> str:
        return "\n".join([
            "Build Agent completed verified workspace patch.",
            f"Instruction: {instruction}",
            f"Changed files: {len(changed)}",
            *(f"- {p}" for p in changed),
            "No Fake Success: real file hashes changed and diff was generated.",
        ])

    def _run_checks(self, root: Path) -> list[str]:
        checks: list[str] = []
        py_files = [p for p in root.rglob("*.py") if not any(part in EXCLUDE_NAMES for part in p.parts)]
        failed = 0
        for path in py_files:
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as exc:
                failed += 1
                checks.append(f"FAIL py_compile {path.relative_to(root)}: {type(exc).__name__}: {exc}")
        if failed == 0:
            checks.append(f"OK py_compile: {len(py_files)} Python files")
        json_files = [p for p in root.rglob("*.json") if not any(part in EXCLUDE_NAMES for part in p.parts)]
        json_failed = 0
        for path in json_files:
            try:
                json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:
                json_failed += 1
                checks.append(f"FAIL json {path.relative_to(root)}: {type(exc).__name__}: {exc}")
        if json_failed == 0:
            checks.append(f"OK json: {len(json_files)} JSON files")
        req = root / "requirements.txt"
        if req.exists():
            checks.append(f"OK requirements.txt present: {req.stat().st_size} bytes")
        else:
            checks.append("WARN requirements.txt not found")
        if (root / ".env").exists():
            checks.append("FAIL .env present inside workspace source")
        else:
            checks.append("OK .env excluded")
        dbs = list(root.rglob("*.db"))
        if dbs:
            checks.append(f"FAIL database files present: {len(dbs)}")
        else:
            checks.append("OK database files excluded")
        return checks

    def _create_test_report(self, root: Path, changed: list[str], checks: list[str]) -> str:
        ok = [c for c in checks if c.startswith("OK")]
        warn = [c for c in checks if c.startswith("WARN")]
        fail = [c for c in checks if c.startswith("FAIL")]
        lines = [
            "M0N4C0 Build Agent Auto Test Report",
            f"Source root: {root}",
            f"Changed files: {len(changed)}",
            f"Checks OK/WARN/FAIL: {len(ok)}/{len(warn)}/{len(fail)}",
            "",
            "Changed files:",
            *(f"- {p}" for p in changed or ["-"]),
            "",
            "Checks:",
            *checks,
        ]
        return "\n".join(lines)

    def _create_export_zip(self, root: Path, output_zip: Path) -> Path:
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in EXCLUDE_NAMES for part in path.parts) or path.suffix.lower() in {".db", ".pyc"}:
                    continue
                rel = path.relative_to(root)
                zf.write(path, rel.as_posix())
        return output_zip

    def _verify_export(self, zip_path: Path, changed_files: list[str]) -> bool:
        if not zip_path.exists():
            return False
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        for p in changed_files:
            if p.startswith("DELETED:"):
                continue
            if p not in names:
                return False
        forbidden = [n for n in names if n.endswith((".db", ".db-wal", ".db-shm", ".pyc")) or n.split("/")[-1] == ".env"]
        return not forbidden
