#!/usr/bin/env python3
"""Update literature tracker data from public scholarly sources.

The script uses only the Python standard library so it can run in GitHub
Actions without dependency installation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "papers.js"

QUERY_GROUPS = [
    {
        "source": "arxiv",
        "query": 'all:"color matching" AND all:"automotive coatings"',
        "topic_hint": "汽车涂料测色",
    },
    {
        "source": "arxiv",
        "query": 'all:"automotive coatings" AND all:"deep learning"',
        "topic_hint": "汽车涂料测色",
    },
    {
        "source": "arxiv",
        "query": 'all:"automotive paint" AND all:"deep learning"',
        "topic_hint": "汽车涂料测色",
    },
    {
        "source": "arxiv",
        "query": 'all:"color recipe" AND all:"machine learning"',
        "topic_hint": "配方推荐",
    },
    {
        "source": "arxiv",
        "query": 'all:"spectral reflectance" AND all:"deep learning" AND all:color',
        "topic_hint": "光谱恢复",
    },
    {
        "source": "arxiv",
        "query": 'all:"structural color" AND all:"deep learning"',
        "topic_hint": "结构色/涂层反设计",
    },
    {
        "source": "crossref",
        "query": '"color matching" "automotive coatings"',
        "topic_hint": "汽车涂料测色",
    },
    {
        "source": "crossref",
        "query": '"paint color matching" "deep learning"',
        "topic_hint": "配方推荐",
    },
    {
        "source": "crossref",
        "query": '"spectral reflectance" "deep learning" color',
        "topic_hint": "光谱恢复",
    },
    {
        "source": "crossref",
        "query": '"automotive coatings" "machine learning" color',
        "topic_hint": "汽车涂料测色",
    },
]

TOPIC_RULES = [
    ("配方推荐", ["recipe", "formulation", "color matching", "colour matching", "kubelka", "pigment mixture"]),
    ("汽车涂料测色", ["automotive coating", "automotive paint", "car paint", "refinish", "multi-angle", "gonio"]),
    ("光谱恢复", ["spectral reflectance", "hyperspectral", "reflectance recovery", "color constancy"]),
    ("效果颜料识别", ["metallic", "pearlescent", "effect pigment", "sparkle", "flop", "brdf"]),
    ("结构色/涂层反设计", ["structural color", "inverse design", "optical coating", "metasurface"]),
    ("生产过程", ["paint shop", "color changeover", "painting quality", "defect"]),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-file", default=str(DATA_FILE))
    parser.add_argument("--limit-per-query", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--offline", action="store_true", help="Only validate and rewrite existing data.")
    args = parser.parse_args()

    data_path = Path(args.data_file)
    data = read_data_file(data_path)
    existing = data.get("papers", [])
    if not isinstance(existing, list):
      raise ValueError("papers must be a list")

    fetched: list[dict[str, Any]] = []
    errors: list[str] = []
    if not args.offline:
        for group in QUERY_GROUPS:
            try:
                if group["source"] == "arxiv":
                    fetched.extend(fetch_arxiv(group["query"], group["topic_hint"], args.limit_per_query))
                elif group["source"] == "crossref":
                    fetched.extend(fetch_crossref(group["query"], group["topic_hint"], args.limit_per_query))
            except Exception as exc:  # noqa: BLE001 - keep scheduled jobs resilient.
                errors.append(f"{group['source']} {group['query']}: {exc}")
            time.sleep(args.sleep)

    merged = merge_papers(existing, fetched)
    output = {
        "generatedAt": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "papers": merged,
        "updateSummary": {
            "existingCount": len(existing),
            "fetchedCount": len(fetched),
            "mergedCount": len(merged),
            "errors": errors,
        },
    }
    write_data_file(data_path, output)

    print(json.dumps(output["updateSummary"], ensure_ascii=False, indent=2))
    if errors:
        print("Warnings:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    return 0


def read_data_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generatedAt": None, "papers": []}
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.LITERATURE_TRACKER_DATA\s*=\s*(\{.*\});?\s*$", text, re.S)
    if not match:
        raise ValueError(f"Cannot parse data file: {path}")
    return json.loads(match.group(1))


def write_data_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(f"window.LITERATURE_TRACKER_DATA = {payload};\n", encoding="utf-8")


def fetch_arxiv(query: str, topic_hint: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"https://export.arxiv.org/api/query?{params}"
    raw = http_get(url)
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    papers: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ns):
        title = clean_text(find_text(entry, "a:title", ns))
        summary = clean_text(find_text(entry, "a:summary", ns))
        authors = ", ".join(clean_text(author.findtext("a:name", default="", namespaces=ns)) for author in entry.findall("a:author", ns))
        published = find_text(entry, "a:published", ns)
        year = int(published[:4]) if published[:4].isdigit() else 0
        url = find_text(entry, "a:id", ns).replace("http://", "https://")
        arxiv_id = url.rsplit("/", 1)[-1]
        topic = infer_topic(f"{title} {summary}", topic_hint)
        papers.append(
            {
                "id": slugify(f"arxiv-{arxiv_id}-{title}"),
                "title": title,
                "authors": authors,
                "year": year,
                "type": "预印本",
                "topic": topic,
                "venue": "arXiv",
                "url": url,
                "relevance": score_relevance(title, summary, topic),
                "status": "未读",
                "tags": infer_tags(title, summary),
                "notes": f"自动发现：{summary[:220]}{'...' if len(summary) > 220 else ''}",
                "source": "arxiv",
                "externalId": arxiv_id,
            }
        )
    return papers


def fetch_crossref(query: str, topic_hint: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query.bibliographic": query,
            "rows": limit,
            "sort": "published",
            "order": "desc",
            "filter": "from-pub-date:2018-01-01,type:journal-article",
            "select": "DOI,title,author,issued,container-title,URL,abstract,subject",
        }
    )
    url = f"https://api.crossref.org/works?{params}"
    raw = http_get(url)
    message = json.loads(raw).get("message", {})
    papers: list[dict[str, Any]] = []
    for item in message.get("items", []):
        title = clean_text(" ".join(item.get("title") or []))
        if not title:
            continue
        abstract = clean_text(strip_tags(item.get("abstract", "")))
        issued = item.get("issued", {}).get("date-parts", [[0]])
        year = issued[0][0] if issued and issued[0] else 0
        authors = ", ".join(format_author(author) for author in item.get("author", [])[:8])
        venue = clean_text(" ".join(item.get("container-title") or [])) or "Crossref"
        doi = item.get("DOI", "")
        url = f"https://doi.org/{doi}" if doi else item.get("URL", "")
        topic = infer_topic(f"{title} {abstract}", topic_hint)
        papers.append(
            {
                "id": slugify(f"doi-{doi or title}"),
                "title": title,
                "authors": authors,
                "year": year,
                "type": "论文",
                "topic": topic,
                "venue": venue,
                "url": url,
                "relevance": score_relevance(title, abstract, topic),
                "status": "未读",
                "tags": infer_tags(title, abstract),
                "notes": f"自动发现：{abstract[:220]}{'...' if len(abstract) > 220 else '待读摘要。'}",
                "source": "crossref",
                "externalId": doi,
            }
        )
    return papers


def http_get(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "color-data-dev-literature-tracker/1.0 (GitHub Actions; scholarly discovery)",
            "Accept": "application/json, application/atom+xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def merge_papers(existing: list[dict[str, Any]], fetched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    keys: set[str] = set()

    for paper in existing:
        normalized = normalize_paper(paper)
        if normalized.get("source") in {"arxiv", "crossref"} and not is_relevant_candidate(normalized):
            continue
        merged.append(normalized)
        keys.update(identity_keys(normalized))

    for paper in sorted(fetched, key=lambda item: (item.get("year") or 0, item.get("relevance") or 0), reverse=True):
        normalized = normalize_paper(paper)
        if not is_relevant_candidate(normalized):
            continue
        paper_keys = identity_keys(normalized)
        if keys.intersection(paper_keys):
            continue
        merged.append(normalized)
        keys.update(paper_keys)

    return sorted(merged, key=lambda item: (item.get("status") != "精读", -(item.get("year") or 0), -int(item.get("relevance") or 0), item.get("title", "")))


def normalize_paper(paper: dict[str, Any]) -> dict[str, Any]:
    year = int(paper.get("year") or 0)
    current_year = dt.datetime.now(dt.UTC).year
    if year > current_year + 1:
        year = 0
    normalized = {
        "id": paper.get("id") or slugify(paper.get("title", "paper")),
        "title": clean_text(paper.get("title", "")),
        "authors": clean_text(paper.get("authors", "")),
        "year": year,
        "type": paper.get("type") or "待分类",
        "topic": paper.get("topic") or "配方推荐",
        "venue": clean_text(paper.get("venue", "")),
        "url": paper.get("url", ""),
        "relevance": max(1, min(5, int(paper.get("relevance") or 3))),
        "status": paper.get("status") or "未读",
        "tags": sorted(set(str(tag).strip() for tag in paper.get("tags", []) if str(tag).strip())),
        "notes": clean_text(paper.get("notes", "")),
    }
    if paper.get("source"):
        normalized["source"] = paper["source"]
    if paper.get("externalId"):
        normalized["externalId"] = paper["externalId"]
    return normalized


def is_relevant_candidate(paper: dict[str, Any]) -> bool:
    if paper.get("source") not in {"arxiv", "crossref"}:
        return True

    text = " ".join(
        [
            paper.get("title", ""),
            paper.get("notes", ""),
            paper.get("topic", ""),
            " ".join(paper.get("tags", [])),
        ]
    ).lower()
    high_precision_terms = [
        "color matching",
        "colour matching",
        "color recipe",
        "spectral reflectance",
        "reflectance spectra",
        "automotive coating",
        "automotive paint",
        "car paint",
        "refinish",
        "pigment mixture",
        "structural color",
        "optical coating",
        "multi-angle",
        "gonio",
        "brdf",
        "paint shop",
    ]
    weak_domain_terms = ["coating", "paint", "pigment", "color", "colour", "spectral", "reflectance"]
    method_terms = ["deep learning", "machine learning", "neural network", "inverse design", "formulation", "recipe"]

    has_precise_term = any(term in text for term in high_precision_terms)
    has_domain_and_method = any(term in text for term in weak_domain_terms) and any(term in text for term in method_terms)
    return paper.get("relevance", 0) >= 3 and (has_precise_term or has_domain_and_method)


def identity_keys(paper: dict[str, Any]) -> set[str]:
    keys = {f"title:{normalize_title(paper.get('title', ''))}"}
    url = paper.get("url", "")
    if url:
        keys.add(f"url:{url.lower().replace('http://', 'https://')}")
    external = paper.get("externalId", "")
    if external:
        keys.add(f"external:{str(external).lower()}")
    return {key for key in keys if not key.endswith(":")}


def infer_topic(text: str, fallback: str) -> str:
    lowered = text.lower()
    best_topic = fallback
    best_hits = 0
    for topic, needles in TOPIC_RULES:
        hits = sum(1 for needle in needles if needle in lowered)
        if hits > best_hits:
            best_topic = topic
            best_hits = hits
    return best_topic


def infer_tags(title: str, abstract: str) -> list[str]:
    lowered = f"{title} {abstract}".lower()
    tags = []
    candidates = {
        "color matching": ["color matching", "colour matching"],
        "automotive coatings": ["automotive coating", "automotive paint", "car paint"],
        "deep learning": ["deep learning", "neural network", "transformer"],
        "machine learning": ["machine learning", "artificial intelligence"],
        "spectral reflectance": ["spectral reflectance", "reflectance spectra"],
        "multi-angle": ["multi-angle", "gonio", "flop"],
        "pigment": ["pigment", "colorant"],
        "recipe": ["recipe", "formulation"],
        "structural color": ["structural color"],
        "BRDF": ["brdf", "bidirectional"],
    }
    for tag, needles in candidates.items():
        if any(needle in lowered for needle in needles):
            tags.append(tag)
    return tags[:8]


def score_relevance(title: str, abstract: str, topic: str) -> int:
    lowered = f"{title} {abstract}".lower()
    score = 1
    strong_terms = ["automotive coating", "automotive paint", "color matching", "colour matching", "recipe", "formulation"]
    method_terms = ["deep learning", "machine learning", "neural network", "spectral reflectance", "multi-angle"]
    score += min(2, sum(1 for term in strong_terms if term in lowered))
    score += min(2, sum(1 for term in method_terms if term in lowered))
    if topic in {"配方推荐", "汽车涂料测色", "光谱恢复"}:
        score += 1
    return max(1, min(5, score))


def format_author(author: dict[str, Any]) -> str:
    given = author.get("given", "")
    family = author.get("family", "")
    return clean_text(f"{given} {family}".strip())


def find_text(entry: ET.Element, path: str, ns: dict[str, str]) -> str:
    value = entry.findtext(path, default="", namespaces=ns)
    return value or ""


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fa5]+", "", value.lower())


def slugify(value: str) -> str:
    text = normalize_title(value)
    asciiish = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (asciiish[:80] or text[:80] or "paper").strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
