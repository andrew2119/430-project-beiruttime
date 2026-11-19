"""Consumer availability guard; all transaction behavior remains in the canonical kernel."""
from importlib import import_module
from bt_contracts_core.errors import PublicError


def get_kernel():
    try:
        kernel=import_module('service_app.kernel')
        if not all(callable(getattr(kernel,name,None)) for name in ['lock_lot','server_now','transition','require_bidding']):
            raise ImportError()
        return kernel
    except ImportError:
        raise PublicError('kernel_unavailable','Auction policy is temporarily unavailable.',status=503) from None
