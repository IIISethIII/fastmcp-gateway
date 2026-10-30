# Google OAuth scopes for the services enabled on workspace-mcp
# (gmail, calendar, tasks, drive, docs, sheets, slides, forms, contacts).
# Must be requested explicitly by the MCP client's OAuth authorization request.
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    # Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    # Calendar
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    # Tasks
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/tasks.readonly",
    # Drive
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
    # Docs
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/documents.readonly",
    # Sheets
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    # Slides
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/presentations.readonly",
    # Forms
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.body.readonly",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    # Contacts
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/contacts.readonly",
]

from fastmcp.client.auth import OAuth  # noqa: E402
from mcp.shared.auth import OAuthClientInformationFull  # noqa: E402


class ScopedOAuth(OAuth):
    """OAuth client that forces the full Google scope set into the flow.

    Two SDK quirks must be worked around:
    1. Workspace-mcp's DCR responses drop the `scope` field, and the mcp SDK
       overwrites client_metadata.scope with the server's advertised (identity
       only) scopes before registering AND authorizing. We monkeypatch the SDK's
       scope-selection function so registration and authorization both use the
       full Google scope list.
    2. We re-assert the scope on the client info right before authorization.
    """

    _scoped_str = " ".join(GOOGLE_SCOPES)

    def __init__(self, *args, **kwargs):
        kwargs.pop("scopes", None)  # scopes come from the class constant
        super().__init__(*args, **kwargs)
        import mcp.client.auth.oauth2 as oauth2

        original = oauth2.get_client_metadata_scopes

        def _always_full_scopes(*args, **kw):
            return ScopedOAuth._scoped_str

        # Keep the original for anything else; only our flow calls this path.
        self._original_scope_selector = original
        oauth2.get_client_metadata_scopes = _always_full_scopes

    async def _perform_authorization(self):
        self.context.client_metadata.scope = self._scoped_str
        client_info = getattr(self.context, "client_info", None)
        if client_info is not None and client_info.scope != self._scoped_str:
            data = client_info.model_dump(exclude_none=True)
            data["scope"] = self._scoped_str
            patched = OAuthClientInformationFull(**data)
            self.context.client_info = patched
            await self.token_storage_adapter.set_client_info(patched)
        return await super()._perform_authorization()

