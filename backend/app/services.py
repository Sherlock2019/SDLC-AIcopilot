"""Process-wide singletons: policy store, tool gateway, context index and git workspaces."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .config import settings
from .core.gateway import ToolGateway
from .core.policy import PolicyStore
from .models import ContextDocument, Policy
from .rag.engine import ContextIndex, Document, load_documents
from .tools.git_local import LocalGit

_store: PolicyStore | None = None
_gateway: ToolGateway | None = None
_index: ContextIndex | None = None


def get_store() -> PolicyStore:
    global _store
    if _store is None:
        _store = PolicyStore.load()
    return _store


def apply_policy_overrides(db: Session) -> None:
    """Re-apply policies a human changed through the UI (persisted in the policies table)."""
    store = get_store()
    for row in db.query(Policy).filter(Policy.active.is_(True)).order_by(Policy.id).all():
        store.set_policy(row.yaml_text, row.source)


def get_gateway() -> ToolGateway:
    global _gateway
    if _gateway is None:
        from .tools.impl import REGISTRY

        _gateway = ToolGateway(get_store(), REGISTRY)
    return _gateway


def get_index() -> ContextIndex:
    global _index
    if _index is None:
        _index = ContextIndex.build(load_documents(settings.context_dir, settings.sample_app_dir / "app"))
    return _index


def rebuild_index(db: Session) -> ContextIndex:
    global _index
    documents = load_documents(settings.context_dir, settings.sample_app_dir / "app")
    for row in db.query(ContextDocument).order_by(ContextDocument.id).all():
        documents.append(Document(row.path, row.text, dict(row.meta or {})))
    _index = ContextIndex.build(documents)
    return _index


def workspace(run_id) -> LocalGit:
    return LocalGit.ensure(settings.data_dir / "workspaces" / f"run-{run_id}", settings.sample_app_dir)


def reset() -> None:
    global _store, _gateway, _index
    _store = _gateway = _index = None
