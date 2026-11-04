from fastapi import Depends
from bt_runtime.app.auth import require_principal
from bt_runtime.auth import Principal


def authorize(principal: Principal = Depends(require_principal)):
    # Add CURRENT domain permission and owned-resource checks before enabling commands.
    return principal
