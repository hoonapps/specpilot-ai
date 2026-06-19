from hashlib import sha1

from fastapi import Header

from specpilot_ai.core.config import get_settings
from specpilot_ai.core.models import WorkspaceContext


def workspace_context(x_specpilot_key: str | None = Header(default=None)) -> WorkspaceContext:
    settings = get_settings()
    if not x_specpilot_key or x_specpilot_key == settings.default_api_key:
        return WorkspaceContext(
            workspace_id=settings.default_workspace_id,
            owner_label="demo-user",
            role="owner",
        )
    digest = sha1(x_specpilot_key.encode()).hexdigest()[:12]
    return WorkspaceContext(
        workspace_id=f"workspace_{digest}",
        owner_label=f"workspace-{digest}",
        role="member",
    )
