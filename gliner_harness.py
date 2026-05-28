from __future__ import annotations

import os

from kg_schema import validate_entity


LABEL_TO_TYPE = {
    "company": "Company",
    "university": "University",
    "research institution": "ResearchInstitution",
    "product": "Product",
    "technology": "Technology",
    "market": "Market",
    "organization": "Organization",
}


def extract_gliner_entities(text: str) -> dict[str, str]:
    try:
        from gliner import GLiNER
    except ImportError as exc:
        raise ImportError(
            "GLiNER is optional. Install it with `pip install gliner` before using --use-gliner."
        ) from exc

    model_name = os.getenv("GLINER_MODEL", "urchade/gliner_multi-v2.1")
    model = GLiNER.from_pretrained(model_name)
    labels = list(LABEL_TO_TYPE)
    predictions = model.predict_entities(text, labels)

    entities: dict[str, str] = {}
    for item in predictions:
        entity_type = LABEL_TO_TYPE.get(item.get("label", ""))
        entity = validate_entity(item.get("text", ""), entity_type)
        if entity:
            entities[entity.name] = entity.type
    return entities
