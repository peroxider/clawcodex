"""Small ontology wrapper for F-154 external configuration imports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_OWL_CLASS_RE = re.compile(r"(?P<name>[A-Za-z_][\w-]*)\s+a\s+owl:Class\b")
_OBJECT_PROPERTY_RE = re.compile(r"(?P<name>[A-Za-z_][\w-]*)\s+a\s+owl:ObjectProperty\b")
_DOMAIN_RE = re.compile(r"rdfs:domain\s+(?:(?:[A-Za-z_][\w-]*):)?(?P<name>[A-Za-z_][\w-]*)")
_RANGE_RE = re.compile(r"rdfs:range\s+(?:(?:[A-Za-z_][\w-]*):)?(?P<name>[A-Za-z_][\w-]*)")


@dataclass(frozen=True)
class OntologyGraph:
    """A parsed ontology subset used by LKB lint and rule checks."""

    source: str
    classes: frozenset[str]
    object_properties: frozenset[str]
    domain_refs: frozenset[str] = frozenset()
    range_refs: frozenset[str] = frozenset()
    graph: Any = None

    def has_class(self, class_name: str) -> bool:
        return class_name in self.classes

    @property
    def item_count(self) -> int:
        return len(self.classes) + len(self.object_properties)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "classes": sorted(self.classes),
            "objectProperties": sorted(self.object_properties),
            "domainRefs": sorted(self.domain_refs),
            "rangeRefs": sorted(self.range_refs),
        }


_ONTOLOGY_REGISTRY: list[OntologyGraph] = []


def load_ontology_turtle(path: Path) -> OntologyGraph:
    """Parse a Turtle ontology, using RDFLib when present and a safe subset fallback."""

    text = path.read_text(encoding="utf-8")
    try:
        return _load_with_rdflib(path, text)
    except ImportError:
        return _load_turtle_subset(path, text)


def merge_ontology_graphs(graphs: tuple[OntologyGraph, ...], *, source: str = "merged") -> OntologyGraph:
    classes: set[str] = set()
    object_properties: set[str] = set()
    domains: set[str] = set()
    ranges: set[str] = set()
    for graph in graphs:
        classes.update(graph.classes)
        object_properties.update(graph.object_properties)
        domains.update(graph.domain_refs)
        ranges.update(graph.range_refs)
    return OntologyGraph(
        source=source,
        classes=frozenset(classes),
        object_properties=frozenset(object_properties),
        domain_refs=frozenset(domains),
        range_refs=frozenset(ranges),
    )


def register_ontology_graph(graph: OntologyGraph, *, force: bool = False) -> None:
    if force:
        _ONTOLOGY_REGISTRY[:] = [g for g in _ONTOLOGY_REGISTRY if g.source != graph.source]
    elif any(g.source == graph.source for g in _ONTOLOGY_REGISTRY):
        raise ValueError(f"ontology source {graph.source!r} already registered")
    _ONTOLOGY_REGISTRY.append(graph)


def get_registered_ontology() -> OntologyGraph | None:
    if not _ONTOLOGY_REGISTRY:
        return None
    return merge_ontology_graphs(tuple(_ONTOLOGY_REGISTRY), source="registry")


def reset_ontology_registry() -> None:
    _ONTOLOGY_REGISTRY.clear()


def _load_with_rdflib(path: Path, text: str) -> OntologyGraph:
    try:
        from rdflib import Graph, RDF, RDFS, OWL
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError from exc

    graph = Graph()
    graph.parse(data=text, format="turtle")
    classes = {_local_name(subject) for subject in graph.subjects(RDF.type, OWL.Class)}
    object_properties = {
        _local_name(subject) for subject in graph.subjects(RDF.type, OWL.ObjectProperty)
    }
    domain_refs = {_local_name(obj) for obj in graph.objects(None, RDFS.domain)}
    range_refs = {_local_name(obj) for obj in graph.objects(None, RDFS.range)}
    return OntologyGraph(
        source=str(path),
        classes=frozenset(filter(None, classes)),
        object_properties=frozenset(filter(None, object_properties)),
        domain_refs=frozenset(filter(None, domain_refs)),
        range_refs=frozenset(filter(None, range_refs)),
        graph=graph,
    )


def _load_turtle_subset(path: Path, text: str) -> OntologyGraph:
    classes = frozenset(match.group("name") for match in _OWL_CLASS_RE.finditer(text))
    object_properties = frozenset(match.group("name") for match in _OBJECT_PROPERTY_RE.finditer(text))
    domain_refs = frozenset(match.group("name") for match in _DOMAIN_RE.finditer(text))
    range_refs = frozenset(match.group("name") for match in _RANGE_RE.finditer(text))
    if not classes and "owl:Class" not in text:
        raise ValueError("ontology turtle file does not declare any owl:Class entries")
    return OntologyGraph(
        source=str(path),
        classes=classes,
        object_properties=object_properties,
        domain_refs=domain_refs,
        range_refs=range_refs,
    )


def _local_name(value: Any) -> str:
    text = str(value)
    if "#" in text:
        return text.rsplit("#", 1)[-1]
    if "/" in text:
        return text.rstrip("/").rsplit("/", 1)[-1]
    return text.split(":", 1)[-1]


__all__ = [
    "OntologyGraph",
    "get_registered_ontology",
    "load_ontology_turtle",
    "merge_ontology_graphs",
    "register_ontology_graph",
    "reset_ontology_registry",
]
