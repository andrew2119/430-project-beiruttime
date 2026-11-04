from bt_contracts.catalog.options import MaterialDetails


def validate(details, component):
    if component not in {"case", "bezel", "dial", "hands", "markers", "strap", "bracelet"}:
        raise ValueError("Material requires a physical component")
    value = MaterialDetails.model_validate(details)
    if value.construction != "solid" and (not value.substrate or not value.thickness_micrometers):
        raise ValueError("Plating and coating require the substrate and thickness")
    if value.construction == "solid" and (value.substrate or value.thickness_micrometers):
        raise ValueError("Solid material cannot claim a coating thickness")
    return value.model_dump(mode="json")
