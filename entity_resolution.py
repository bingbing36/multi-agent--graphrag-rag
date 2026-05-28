from __future__ import annotations

from kg_schema import KGEntity, KGRelation, clean_name


CANONICAL_ALIASES = {
    "小米": "小米科技有限责任公司",
    "小米科技": "小米科技有限责任公司",
    "华为": "华为技术有限公司",
    "苹果": "苹果公司",
    "Apple": "苹果公司",
    "AppleInc.": "苹果公司",
    "微软": "微软",
    "Microsoft": "微软",
    "谷歌": "谷歌",
    "Google": "谷歌",
    "英特尔": "英特尔",
    "Intel": "英特尔",
}


def resolve_entity_name(name: str) -> str:
    clean = clean_name(name)
    return CANONICAL_ALIASES.get(clean, clean)


def resolve_entities(entities: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for name, entity_type in entities.items():
        canonical = resolve_entity_name(name)
        resolved[canonical] = entity_type
    return resolved


def resolve_relations(relations: list[KGRelation]) -> list[KGRelation]:
    deduped: dict[tuple[str, str, str], KGRelation] = {}
    for relation in relations:
        source = resolve_entity_name(relation.source)
        target = resolve_entity_name(relation.target)
        key = (source, relation.relation, target)
        deduped[key] = KGRelation(source, relation.relation, target)
    return list(deduped.values())


def resolve_entity(entity: KGEntity) -> KGEntity:
    return KGEntity(resolve_entity_name(entity.name), entity.type)
