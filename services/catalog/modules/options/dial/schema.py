from bt_contracts.catalog.options import DialDetails


def validate(details, component):
    if component != "dial":
        raise ValueError("Dial design requires the dial component")
    return DialDetails.model_validate(details).model_dump(mode="json")
