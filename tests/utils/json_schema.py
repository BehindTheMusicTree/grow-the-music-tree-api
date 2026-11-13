def property_names(schema) -> set[str]:
    """Every property name a JSON Schema declares, at any depth."""
    names: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names |= set(value)
            names |= property_names(value)
    elif isinstance(schema, list):
        for item in schema:
            names |= property_names(item)
    return names


def keys_used(value) -> set[str]:
    """Every object key a sample document uses, at any depth."""
    keys: set[str] = set()
    if isinstance(value, dict):
        keys |= set(value)
        for item in value.values():
            keys |= keys_used(item)
    elif isinstance(value, list):
        for item in value:
            keys |= keys_used(item)
    return keys
