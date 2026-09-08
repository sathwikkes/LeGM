"""Save/load DraftState as JSON under data/drafts/<draft_id>.json."""

from __future__ import annotations

from pathlib import Path

from legm.draft.models import DraftState

DEFAULT_DRAFT_DIR = Path("data") / "drafts"


def draft_path(draft_id: str, directory: Path = DEFAULT_DRAFT_DIR) -> Path:
    return Path(directory) / f"{draft_id}.json"


def save_draft(state: DraftState, directory: Path = DEFAULT_DRAFT_DIR) -> Path:
    path = draft_path(state.draft_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(), encoding="utf-8")
    tmp.replace(path)  # atomic on POSIX so a crash mid-write cannot corrupt the draft
    return path


def load_draft(draft_id: str, directory: Path = DEFAULT_DRAFT_DIR) -> DraftState:
    path = draft_path(draft_id, directory)
    if not path.exists():
        raise FileNotFoundError(f"no draft {draft_id!r} in {directory}")
    return DraftState.model_validate_json(path.read_text(encoding="utf-8"))


def list_drafts(directory: Path = DEFAULT_DRAFT_DIR) -> list[str]:
    """Draft ids, most recently modified first."""
    directory = Path(directory)
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files]
