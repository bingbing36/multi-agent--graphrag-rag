from __future__ import annotations

from kg_schema import KGRelation


EXPECTED_RELATIONS = {
    ("小米科技有限责任公司", "DEVELOPS", "120W超快闪充技术"),
    ("小米科技有限责任公司", "PARTNERS_WITH", "Adobe"),
    ("小米科技有限责任公司", "PARTNERS_WITH", "微软"),
    ("华为技术有限公司", "DEVELOPS", "5G网络技术"),
    ("华为技术有限公司", "DEVELOPS", "云计算"),
    ("华为技术有限公司", "DEVELOPS", "大数据解决方案"),
    ("华为技术有限公司", "DEVELOPS", "人工智能"),
    ("华为技术有限公司", "DEVELOPS", "鸿蒙操作系统"),
    ("华为技术有限公司", "COOPERATES_WITH", "剑桥大学"),
    ("苹果公司", "DEVELOPS", "MacBook"),
    ("苹果公司", "DEVELOPS", "iPhone"),
    ("苹果公司", "PARTNERS_WITH", "英特尔"),
    ("苹果公司", "PARTNERS_WITH", "谷歌"),
}


def evaluate_relations(relations: list[KGRelation]) -> dict[str, object]:
    actual = {(item.source, item.relation, item.target) for item in relations}
    hits = sorted(EXPECTED_RELATIONS & actual)
    missing = sorted(EXPECTED_RELATIONS - actual)
    extra = sorted(actual - EXPECTED_RELATIONS)
    return {
        "expected": len(EXPECTED_RELATIONS),
        "actual": len(actual),
        "hits": len(hits),
        "missing": missing,
        "extra": extra,
    }


def print_eval_report(relations: list[KGRelation]) -> None:
    report = evaluate_relations(relations)
    print(
        "KG eval: "
        f"hits={report['hits']}/{report['expected']}, "
        f"actual_relations={report['actual']}"
    )
    missing = report["missing"]
    if missing:
        print("Missing expected relations:")
        for item in missing[:10]:
            print(f"  - {item}")
    extra = report["extra"]
    if extra:
        print("Extra relations preview:")
        for item in extra[:10]:
            print(f"  - {item}")
