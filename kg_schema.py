from __future__ import annotations

import re
from dataclasses import dataclass


ALLOWED_ENTITY_TYPES = {
    "Company",
    "University",
    "ResearchInstitution",
    "Product",
    "Technology",
    "Market",
    "Organization",
    "Project",
    "Material",
}

ALLOWED_RELATIONS = {
    "DEVELOPS",
    "PRODUCES",
    "COOPERATES_WITH",
    "PARTNERS_WITH",
    "EXPANDS_TO",
    "SUPPORTS",
    "USES_MATERIAL",
    "SPONSORS",
}

RELATION_ALIASES = {
    "HAS_RESEARCH_CENTER": "DEVELOPS",
    "PARTNERED_WITH": "PARTNERS_WITH",
    "WORKS_WITH": "PARTNERS_WITH",
    "BUILDS": "DEVELOPS",
    "CREATES": "DEVELOPS",
    "LAUNCHES": "PRODUCES",
}


@dataclass(frozen=True)
class KGEntity:
    name: str
    type: str


@dataclass(frozen=True)
class KGRelation:
    source: str
    relation: str
    target: str


def clean_name(text: str) -> str:
    name = str(text or "").strip()
    name = re.sub(r"\s+", "", name)
    name = name.strip("，。；;,.、:：()（）[]【】\"' ")
    return name


def classify_entity(name: str, proposed_type: str | None = None) -> str | None:
    proposed = (proposed_type or "").strip()
    if proposed in ALLOWED_ENTITY_TYPES:
        return proposed
    if name in {"Adobe", "微软", "Microsoft", "谷歌", "Google", "英特尔", "Intel"}:
        return "Company"
    if any(suffix in name for suffix in ("有限公司", "集团", "公司", "科技", "技术股份")):
        return "Company"
    if any(suffix in name for suffix in ("大学", "学院")):
        return "University"
    if any(keyword in name for keyword in ("研究机构", "研究院", "实验室")):
        return "ResearchInstitution"
    if any(keyword in name for keyword in ("市场", "欧洲", "亚洲", "非洲", "印度", "东南亚", "美国", "中国")):
        return "Market"
    if any(keyword in name for keyword in ("技术", "云计算", "人工智能", "解决方案", "芯片", "算法")):
        return "Technology"
    if any(keyword in name for keyword in ("项目", "计划")):
        return "Project"
    if any(keyword in name for keyword in ("材料")):
        return "Material"
    if any(keyword in name for keyword in ("运营商", "政府", "企业", "俱乐部", "制片厂", "制作公司")):
        return "Organization"
    if 1 < len(name) <= 50:
        return "Product"
    return None


def normalize_relation(relation: str) -> str | None:
    rel = str(relation or "").strip().upper()
    rel = RELATION_ALIASES.get(rel, rel)
    return rel if rel in ALLOWED_RELATIONS else None


def validate_entity(name: str, proposed_type: str | None = None) -> KGEntity | None:
    clean = clean_name(name)
    if not clean or len(clean) < 2:
        return None
    entity_type = classify_entity(clean, proposed_type)
    if not entity_type:
        return None
    return KGEntity(clean, entity_type)


def validate_relation(source: str, relation: str, target: str) -> KGRelation | None:
    src = clean_name(source)
    dst = clean_name(target)
    rel = normalize_relation(relation)
    if not src or not dst or not rel or src == dst:
        return None
    return KGRelation(src, rel, dst)
