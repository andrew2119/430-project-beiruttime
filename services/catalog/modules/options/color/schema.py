from bt_contracts.catalog.options import ColorDetails


def validate(details, component):
    if component not in {"case", "bezel", "dial", "hands", "markers", "strap", "bracelet"}:
        raise ValueError("Color requires a physical component")
    return ColorDetails.model_validate(details).model_dump(mode="json")
