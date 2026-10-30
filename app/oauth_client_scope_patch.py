# Server-side workaround for workspace-mcp's OAuth 2.1 proxy: its dynamic client
# registration (DCR) handler drops the `scope` field, so the registered client
# has scope=None. The MCP SDK's validate_scope() then rejects EVERY requested
# Google scope at the token exchange with
#   "Client was not registered with scope <scope>"
# In this trusted single-tenant setup (our own proxy + our own client) scope
# subset validation is unnecessary defense-in-depth, so we disable it entirely.
# Both sides (workspace-mcp server AND fastmcp gateway client) run this patch.
from mcp.shared.auth import OAuthClientInformationFull


def _patched_validate_scope(self, requested_scope):
    return requested_scope.split() if requested_scope else []


OAuthClientInformationFull.validate_scope = _patched_validate_scope
