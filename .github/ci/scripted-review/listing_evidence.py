"""The one JSON encoding the scripted review's files use. Test only, not physical inspection."""
import json


def encode(value):
    return json.dumps(value,sort_keys=True).encode()
