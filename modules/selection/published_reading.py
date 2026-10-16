"""Published score reading owned by the selection module."""
import json
from typing import Any
from core.catalog.published_reading import plain_published_value
from core.catalog._port_value_codec import _wire_to_value
from datatypes.observation import observation_context_profile, observation_context_profile_descriptor

def read_scores(encoded: bytes) -> dict[str, Any]:
    fields = json.loads(encoded)["value"]["fields"]
    entries = []
    for encoded_entry in fields["entries"]:
        entry = plain_published_value(encoded_entry)
        context = _wire_to_value(encoded_entry["fields"]["context"])
        entry["context_profile"] = observation_context_profile_descriptor(
            observation_context_profile(context),
        )
        entries.append(entry)
    return {"collection_id": fields["collection_id"], "entries": entries}
