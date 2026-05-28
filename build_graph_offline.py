from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_community.graphs import Neo4jGraph
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from neo4j import GraphDatabase

from config import BASE_DIR, COMPANY_DOC_PATH, PROJECT_ROOT, get_graph_llm, require_env
from entity_resolution import resolve_entities, resolve_entity_name, resolve_relations
from gliner_harness import extract_gliner_entities
from kg_eval import print_eval_report
from kg_schema import KGEntity, KGRelation, validate_entity, validate_relation


RELATION_LABELS = {
    "DEVELOPS",
    "PRODUCES",
    "COOPERATES_WITH",
    "PARTNERS_WITH",
    "EXPANDS_TO",
    "SUPPORTS",
    "USES_MATERIAL",
    "SPONSORS",
}


def resolve_company_doc_path() -> Path:
    path = Path(COMPANY_DOC_PATH)
    if path.is_absolute():
        return path
    local_default = (BASE_DIR / "doc" / "company.txt").resolve()
    if ".." in path.parts and local_default.exists():
        return local_default
    first = (BASE_DIR / path).resolve()
    if first.exists():
        return first
    return (PROJECT_ROOT / path).resolve()


def strip_parenthetical(text: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", text).strip()


def split_items(text: str) -> list[str]:
    cleaned = re.sub(r"(等|系列|方面|领域|项目|服务)$", "", text.strip())
    parts = re.split(r"[、，,]|以及|和|与", cleaned)
    return [item.strip(" 。；;") for item in parts if item.strip(" 。；;")]


def find_company_sections(text: str) -> list[tuple[str, str]]:
    header_pattern = re.compile(r"(?m)^([^\n：:]{2,60}公司(?:[（(][^）)]*[）)])?)[：:]")
    matches = list(header_pattern.finditer(text))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        raw_name = strip_parenthetical(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        company = resolve_entity_name(raw_name)
        sections.append((company, text[start:end]))
    return sections


def add_entity(entities: dict[str, str], name: str, proposed_type: str | None = None) -> str | None:
    canonical = resolve_entity_name(name)
    entity = validate_entity(canonical, proposed_type)
    if not entity:
        return None
    entities[entity.name] = entity.type
    return entity.name


def add_relation(
    entities: dict[str, str],
    relations: list[KGRelation],
    source: str,
    relation: str,
    target: str,
    target_type: str | None = None,
) -> None:
    src = add_entity(entities, source, "Company")
    dst = add_entity(entities, target, target_type)
    if not src or not dst:
        return
    guarded = validate_relation(src, relation, dst)
    if guarded:
        relations.append(guarded)


def extract_markets(company: str, body: str, entities: dict[str, str], relations: list[KGRelation]) -> None:
    market_keywords = ("印度", "东南亚", "欧洲", "美国", "中国", "亚洲", "非洲")
    for market in market_keywords:
        if market in body:
            add_relation(entities, relations, company, "EXPANDS_TO", f"{market}市场", "Market")


def extract_partners(company: str, body: str, entities: dict[str, str], relations: list[KGRelation]) -> None:
    known_partners = ("Adobe", "微软", "英特尔", "谷歌", "当地电信运营商", "地方政府")
    for partner in known_partners:
        if partner in body:
            add_relation(entities, relations, company, "PARTNERS_WITH", partner, None)

    for match in re.finditer(r"与([^。；\n]{2,80}?)(?:合作|建立了合作|建立了战略合作)", body):
        phrase = match.group(1)
        for item in split_items(phrase):
            if "剑桥大学" in item:
                add_relation(entities, relations, company, "COOPERATES_WITH", "剑桥大学", "University")
            elif "研究机构" in item:
                add_relation(
                    entities,
                    relations,
                    company,
                    "COOPERATES_WITH",
                    "全球多家顶尖大学和研究机构",
                    "ResearchInstitution",
                )


def extract_products_and_tech(company: str, body: str, entities: dict[str, str], relations: list[KGRelation]) -> None:
    known_terms = {
        "120W超快闪充技术": "Technology",
        "1亿像素手机摄像头": "Product",
        "5G网络技术": "Technology",
        "云计算": "Technology",
        "大数据解决方案": "Technology",
        "人工智能": "Technology",
        "鸿蒙操作系统": "Product",
        "MacBook": "Product",
        "iPhone": "Product",
        "Siri语音助手": "Product",
        "面部识别技术": "Technology",
        "iCloud": "Product",
        "AppleMusic": "Product",
        "AppStore": "Product",
        "下一代光通信技术": "Technology",
    }
    for term, entity_type in known_terms.items():
        if term in body:
            add_relation(entities, relations, company, "DEVELOPS", term, entity_type)


def extract_social_and_brand(company: str, body: str, entities: dict[str, str], relations: list[KGRelation]) -> None:
    if "小米基金会" in body:
        add_relation(entities, relations, company, "SUPPORTS", "小米基金会", "Organization")
    if "教育项目" in body:
        add_relation(entities, relations, company, "SUPPORTS", "教育项目", "Project")
    if "科技创新项目" in body:
        add_relation(entities, relations, company, "SUPPORTS", "科技创新项目", "Project")
    if "环保材料" in body:
        add_relation(entities, relations, company, "USES_MATERIAL", "环保材料", "Material")
    if "欧洲足球俱乐部" in body:
        add_relation(entities, relations, company, "SPONSORS", "欧洲足球俱乐部", "Organization")


def extract_entities_relations(text: str) -> tuple[dict[str, str], list[KGRelation]]:
    entities: dict[str, str] = {}
    relations: list[KGRelation] = []

    for company, body in find_company_sections(text):
        add_entity(entities, company, "Company")
        extract_products_and_tech(company, body, entities, relations)
        extract_markets(company, body, entities, relations)
        extract_partners(company, body, entities, relations)
        extract_social_and_brand(company, body, entities, relations)

    resolved_entities = resolve_entities(entities)
    resolved_relations = resolve_relations(relations)
    return resolved_entities, resolved_relations


def split_documents(doc_path: Path):
    loader = TextLoader(str(doc_path), encoding="utf-8")
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
    return splitter.split_documents(docs)


def neo4j_uri_candidates() -> list[str]:
    configured = require_env("NEO4J_URL")
    candidates = [configured]
    if configured.startswith("neo4j+s://"):
        candidates.append(configured.replace("neo4j+s://", "bolt+s://", 1))
    elif configured.startswith("neo4j://"):
        candidates.append(configured.replace("neo4j://", "bolt://", 1))
    return candidates


def preview_llm_graph_transformer(doc_path: Path) -> tuple[int, str]:
    graph = Neo4jGraph(
        url=neo4j_uri_candidates()[0],
        username=require_env("NEO4J_USERNAME"),
        password=require_env("NEO4J_PASSWORD"),
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    docs = split_documents(doc_path)
    transformer = LLMGraphTransformer(llm=get_graph_llm(), ignore_tool_usage=True)
    graph_docs = transformer.convert_to_graph_documents(docs)
    if graph_docs:
        print(f"Nodes from 1st graph doc: {graph_docs[0].nodes}")
        print(f"Relationships from 1st graph doc: {graph_docs[0].relationships}")
    if os.getenv("ENABLE_LLM_GRAPH_SUPPLEMENT", "false").lower() in {"1", "true", "yes"}:
        graph.add_graph_documents(graph_docs)
        return len(graph_docs), f"LLMGraphTransformer imported {len(graph_docs)} graph document blocks."
    return len(graph_docs), f"LLMGraphTransformer previewed {len(graph_docs)} blocks; import disabled."


def create_constraints(session) -> None:
    session.run("CREATE CONSTRAINT company_name IF NOT EXISTS FOR (n:Company) REQUIRE n.name IS UNIQUE")
    session.run("CREATE CONSTRAINT university_name IF NOT EXISTS FOR (n:University) REQUIRE n.name IS UNIQUE")
    session.run(
        "CREATE CONSTRAINT research_name IF NOT EXISTS FOR (n:ResearchInstitution) REQUIRE n.name IS UNIQUE"
    )
    session.run("CREATE CONSTRAINT product_name IF NOT EXISTS FOR (n:Product) REQUIRE n.name IS UNIQUE")
    session.run("CREATE CONSTRAINT technology_name IF NOT EXISTS FOR (n:Technology) REQUIRE n.name IS UNIQUE")
    session.run("CREATE CONSTRAINT market_name IF NOT EXISTS FOR (n:Market) REQUIRE n.name IS UNIQUE")
    session.run("CREATE CONSTRAINT organization_name IF NOT EXISTS FOR (n:Organization) REQUIRE n.name IS UNIQUE")
    session.run("CREATE CONSTRAINT project_name IF NOT EXISTS FOR (n:Project) REQUIRE n.name IS UNIQUE")
    session.run("CREATE CONSTRAINT material_name IF NOT EXISTS FOR (n:Material) REQUIRE n.name IS UNIQUE")


def reset_graph(session) -> None:
    session.run("MATCH (n) DETACH DELETE n")


def upsert_entity(session, entity: KGEntity) -> None:
    query = f"MERGE (n:{entity.type} {{name: $name}})"
    session.run(query, name=entity.name)


def upsert_relation(session, relation: KGRelation, entities: dict[str, str]) -> None:
    source_type = entities.get(relation.source)
    target_type = entities.get(relation.target)
    if not source_type or not target_type or relation.relation not in RELATION_LABELS:
        return
    query = (
        f"MATCH (a:{source_type} {{name: $source}}) "
        f"MATCH (b:{target_type} {{name: $target}}) "
        f"MERGE (a)-[:{relation.relation}]->(b)"
    )
    session.run(query, source=relation.source, target=relation.target)


def import_clean_graph(entities: dict[str, str], relations: list[KGRelation], *, reset: bool) -> None:
    last_error: Exception | None = None
    for uri in neo4j_uri_candidates():
        driver = GraphDatabase.driver(
            uri,
            auth=(require_env("NEO4J_USERNAME"), require_env("NEO4J_PASSWORD")),
        )
        try:
            with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
                if reset:
                    reset_graph(session)
                create_constraints(session)
                for name, entity_type in entities.items():
                    upsert_entity(session, KGEntity(name, entity_type))
                for relation in relations:
                    upsert_relation(session, relation, entities)
            print(f"Neo4j import used URI: {uri}")
            return
        except Exception as exc:
            last_error = exc
            print(f"Neo4j import failed with URI {uri}: {exc}")
        finally:
            driver.close()
    if last_error:
        raise last_error


def print_preview(entities: dict[str, str], relations: list[KGRelation]) -> None:
    print(f"Schema guard entities={len(entities)}, relations={len(relations)}")
    print("Entities preview:")
    for name, entity_type in sorted(entities.items())[:30]:
        print(f"  - ({entity_type}) {name}")
    print("Relations preview:")
    for relation in relations[:40]:
        print(f"  - {relation.source} -[{relation.relation}]-> {relation.target}")


def build_graph_once(
    *,
    dry_run: bool = False,
    reset: bool = False,
    preview_llm: bool = False,
    use_gliner: bool = False,
) -> None:
    doc_path = resolve_company_doc_path()
    if not doc_path.exists():
        raise FileNotFoundError(f"Company corpus not found: {doc_path}")

    print(f"Using corpus: {doc_path}")
    text = doc_path.read_text(encoding="utf-8")
    entities, relations = extract_entities_relations(text)
    if use_gliner:
        gliner_entities = extract_gliner_entities(text)
        entities.update(resolve_entities(gliner_entities))
        print(f"GLiNER added candidate entities={len(gliner_entities)}")
    print_preview(entities, relations)
    print_eval_report(relations)

    if dry_run:
        print("Dry run completed. Neo4j was not modified.")
        return

    import_clean_graph(entities, relations, reset=reset)
    print(f"Clean graph imported. entities={len(entities)}, relations={len(relations)}, reset={reset}")

    if preview_llm:
        try:
            _, message = preview_llm_graph_transformer(doc_path)
            print(message)
        except Exception as exc:
            print(f"LLMGraphTransformer preview skipped: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a schema-guarded Neo4j knowledge graph.")
    parser.add_argument("--dry-run", action="store_true", help="Preview extracted entities and relations only.")
    parser.add_argument("--reset", action="store_true", help="Delete existing Neo4j data before importing.")
    parser.add_argument("--preview-llm", action="store_true", help="Preview LLMGraphTransformer output.")
    parser.add_argument("--use-gliner", action="store_true", help="Use optional GLiNER NER candidate extraction.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_graph_once(
        dry_run=args.dry_run,
        reset=args.reset,
        preview_llm=args.preview_llm,
        use_gliner=args.use_gliner,
    )
