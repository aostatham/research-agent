"""
Knowledge graph store using Kuzu.

KuzuStore wraps a Kuzu embedded graph database for cross-run evidence
persistence. The graph schema stores research claims, sources, topics, and
their relationships to support contradiction detection, supersession tracking,
and corroboration scoring across runs.

All public methods return JSON strings and never raise — the knowledge store
must not crash the research pipeline (D042 pattern).
"""

import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Module-level singleton ─────────────────────────────────────────────────────

_store = None


def configure_knowledge(config) -> None:
    """
    Configure the module-level knowledge store from config.

    Called once at startup in main(). Sets the module-level _store singleton.
    If knowledge_store is "none", _store is set to None (no-op store).

    Args:
        config: Config instance with knowledge_store and knowledge_db_path fields.

    Raises:
        ValueError: If config.knowledge_store is not "none" or "kuzu".
    """
    global _store
    if config.knowledge_store == "none":
        _store = None
        return
    if config.knowledge_store == "kuzu":
        _store = KuzuStore(config.knowledge_db_path)
        return
    raise ValueError(f"Unknown knowledge_store: {config.knowledge_store!r}. "
                     f"Valid values: none, kuzu")


def get_store():
    """Return the module-level KuzuStore, or None if not configured."""
    return _store


# ── Schema DDL ─────────────────────────────────────────────────────────────────

_NODE_TABLES = [
    """CREATE NODE TABLE IF NOT EXISTS Topic(
        name STRING,
        PRIMARY KEY(name)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Claim(
        claim_id STRING,
        claim_text STRING,
        confidence DOUBLE,
        verification_status STRING,
        evidence_type STRING,
        retrieved STRING,
        PRIMARY KEY(claim_id)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Source(
        url STRING,
        title STRING,
        source_type STRING,
        retrieved STRING,
        PRIMARY KEY(url)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Run(
        run_id STRING,
        started_at STRING,
        PRIMARY KEY(run_id)
    )""",
    """CREATE NODE TABLE IF NOT EXISTS Entity(
        name STRING,
        PRIMARY KEY(name)
    )""",
]

_REL_TABLES = [
    "CREATE REL TABLE IF NOT EXISTS SUPPORTED_BY(FROM Claim TO Source)",
    "CREATE REL TABLE IF NOT EXISTS CONTRADICTS(FROM Claim TO Claim)",
    "CREATE REL TABLE IF NOT EXISTS SUPERSEDES(FROM Claim TO Claim)",
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO(FROM Claim TO Topic)",
    "CREATE REL TABLE IF NOT EXISTS PRECEDED_BY(FROM Topic TO Topic)",
]

# LLM refusal prefixes — duplicated from provenance.py per D042 (gate at both points).
# Do not import from provenance.py; provenance.py has no imports from knowledge/.
_REFUSAL_PREFIXES = (
    "i cannot", "i can't", "i'm unable", "i am unable",
    "as an ai", "as a language model",
)


class KuzuStore:
    """
    Embedded knowledge graph store backed by Kuzu.

    Persists research claims, sources, and topics across runs. Supports
    contradiction detection, supersession tracking, and related-topic queries.

    All public methods catch all exceptions and return JSON strings — the
    knowledge store must not crash the research pipeline.
    """

    def __init__(self, db_path: str):
        """
        Open or create the Kuzu database at db_path.

        Creates all node and relationship tables if they do not exist.
        On any failure, marks the store as unavailable — all subsequent
        method calls return error JSON rather than raising.

        Args:
            db_path: Path to the Kuzu database directory.
        """
        try:
            import kuzu
            parent = os.path.dirname(os.path.abspath(db_path))
            os.makedirs(parent, exist_ok=True)
            self.db = kuzu.Database(db_path)
            self.conn = kuzu.Connection(self.db)
            self._create_schema()
            self._available = True
        except Exception as e:
            logger.warning("KuzuStore: failed to open database at %r: %s", db_path, e)
            self.db = None
            self.conn = None
            self._available = False

    def _create_schema(self) -> None:
        """Create all node and relationship tables if they do not exist."""
        for ddl in _NODE_TABLES:
            self.conn.execute(ddl)
        for ddl in _REL_TABLES:
            self.conn.execute(ddl)

    def close(self) -> None:
        """Close the connection."""
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    # ── Writes ─────────────────────────────────────────────────────────────────

    def write_run(self, run_id: str, topic: str, claims: list,
                  sources: list, started_at: str) -> None:
        """
        Persist a research run's claims and sources to the knowledge graph.

        Merges (upserts) the Run and Topic nodes. For each valid claim, merges
        the Claim node and creates a BELONGS_TO edge to the Topic. Creates
        SUPERSEDES edges for newer claims over older claims on the same topic.
        Creates CONTRADICTS edges between verified and refuted claims on the
        same topic. For each source in the flat sources list and in each
        claim's sources list, merges the Source node and creates SUPPORTED_BY
        edges from each claim to its sources.

        Invalid claims are skipped with a WARNING log.

        Args:
            run_id:     Unique run identifier.
            topic:      Research topic string.
            claims:     List of EvidenceClaim dicts.
            sources:    Flat deduplicated list of EvidenceSource dicts.
            started_at: ISO timestamp of when the run started.
        """
        if not self._available:
            return
        try:
            self._merge_run(run_id, started_at)
            self._merge_topic(topic)

            written: list[tuple[str, dict]] = []
            for idx, claim in enumerate(claims):
                if not self._is_valid_graph_claim(claim):
                    logger.warning(
                        "KuzuStore.write_run: skipping invalid claim: %r",
                        str(claim.get("claim", ""))[:60],
                    )
                    continue
                claim_id = f"{run_id}_{claim.get('id', idx)}"
                self._merge_claim(claim_id, claim)
                self._create_edge(
                    "MATCH (c:Claim {claim_id: $a}), (t:Topic {name: $b}) "
                    "CREATE (c)-[:BELONGS_TO]->(t)",
                    {"a": claim_id, "b": topic},
                )
                written.append((claim_id, claim))

            # Post-process temporal and contradiction edges
            self._create_temporal_edges(topic, written)
            self._create_contradiction_edges(topic, written)

            # Merge flat sources list
            for source in sources:
                if source.get("url"):
                    self._merge_source(source)

            # Merge per-claim sources and SUPPORTED_BY edges
            for claim_id, claim in written:
                for src in claim.get("sources", []):
                    url = src.get("url", "")
                    if url:
                        self._merge_source(src)
                        self._create_edge(
                            "MATCH (c:Claim {claim_id: $a}), (s:Source {url: $b}) "
                            "CREATE (c)-[:SUPPORTED_BY]->(s)",
                            {"a": claim_id, "b": url},
                        )

        except Exception as e:
            logger.warning("KuzuStore.write_run: unexpected error: %s", e)

    def write_claim(self, claim: dict) -> str:
        """
        Validate and write a single claim to the graph.

        Returns:
            JSON string: {"status": "written", "claim_id": "..."} on success,
            {"status": "rejected", "reason": "..."} on validation failure,
            {"status": "error", "reason": "..."} on unexpected error.
            Never raises.
        """
        if not self._available:
            return json.dumps({"status": "error",
                               "reason": "knowledge graph unavailable"})
        if not self._is_valid_graph_claim(claim):
            return json.dumps({"status": "rejected",
                               "reason": _rejection_reason(claim)})
        try:
            claim_id = claim.get("claim_id") or str(_uuid.uuid4())
            self._merge_claim(claim_id, claim)
            return json.dumps({"status": "written", "claim_id": claim_id})
        except Exception as e:
            return json.dumps({"status": "error", "reason": str(e)})

    # ── Reads ──────────────────────────────────────────────────────────────────

    def query_claims_for_topic(self, topic: str) -> str:
        """
        Return all claims for a topic as a JSON string.

        Returns:
            JSON array of claim objects (with nested sources) when claims exist.
            "[]" when no claims are found.
            '{"error": "knowledge graph unavailable"}' when unavailable.
        """
        if not self._available:
            return '{"error": "knowledge graph unavailable"}'
        try:
            result = self.conn.execute(
                "MATCH (c:Claim)-[:BELONGS_TO]->(t:Topic {name: $topic}) "
                "OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(s:Source) "
                "RETURN c.claim_id, c.claim_text, c.confidence, "
                "c.verification_status, c.retrieved, s.url, s.source_type",
                {"topic": topic},
            )
            by_id: dict = {}
            while result.has_next():
                row = result.get_next()
                cid, ctext, conf, vstatus, retrieved, src_url, src_type = row
                if cid not in by_id:
                    by_id[cid] = {
                        "claim_id": cid,
                        "claim": ctext,
                        "confidence": conf,
                        "verification_status": vstatus,
                        "retrieved": retrieved or "",
                        "sources": [],
                    }
                if src_url:
                    by_id[cid]["sources"].append({
                        "url": src_url,
                        "source_type": src_type or "general",
                    })
            return json.dumps(list(by_id.values()))
        except Exception as e:
            logger.warning("KuzuStore.query_claims_for_topic: %s", e)
            return '{"error": "knowledge graph unavailable"}'

    def check_contradiction(self, claim_text: str, topic: str,
                            staleness_days: int = 90) -> str:
        """
        Check the graph for explicit CONTRADICTS edges among claims on the topic.

        Staleness check: if the two contradicting claims' retrieved dates are
        more than staleness_days apart, returns unresolved rather than
        contradiction_found (D037).

        Returns:
            JSON string with one of three statuses:
            - contradiction_found: a CONTRADICTS edge exists within staleness window
            - unresolved: no graph evidence, graph unavailable, or staleness exceeded
            - no_contradiction: topic exists but no CONTRADICTS edges found
        """
        if not self._available:
            return json.dumps({"status": "unresolved",
                               "reason": "knowledge graph unavailable"})
        try:
            result = self.conn.execute(
                "MATCH (c1:Claim)-[:BELONGS_TO]->(t:Topic {name: $topic}), "
                "(c2:Claim)-[:BELONGS_TO]->(t), "
                "(c1)-[:CONTRADICTS]->(c2) "
                "WHERE c1.claim_text CONTAINS $claim_text "
                "   OR c2.claim_text CONTAINS $claim_text "
                "RETURN c1.claim_text, c1.retrieved, c2.claim_text, c2.retrieved, "
                "c1.confidence, c2.confidence "
                "LIMIT 1",
                {"topic": topic, "claim_text": claim_text},
            )
            if not result.has_next():
                return json.dumps({"status": "no_contradiction"})

            row = result.get_next()
            c1_text, c1_retrieved, c2_text, c2_retrieved, c1_conf, c2_conf = row

            # Staleness: if the two claims' timestamps are more than staleness_days apart
            if c1_retrieved and c2_retrieved:
                try:
                    d1 = datetime.fromisoformat(c1_retrieved.replace("Z", "+00:00"))
                    d2 = datetime.fromisoformat(c2_retrieved.replace("Z", "+00:00"))
                    delta = abs((d1 - d2).days)
                    if delta > staleness_days:
                        return json.dumps({
                            "status": "unresolved",
                            "reason": f"potential staleness: claims are {delta} days apart",
                        })
                except (ValueError, AttributeError):
                    pass

            confidence_delta = round(abs((c1_conf or 0.0) - (c2_conf or 0.0)), 4)
            return json.dumps({
                "status": "contradiction_found",
                "contradicting_claim": c2_text,
                "claim_retrieved": c1_retrieved or "",
                "contradicting_retrieved": c2_retrieved or "",
                "confidence_delta": confidence_delta,
            })
        except Exception as e:
            return json.dumps({"status": "unresolved", "reason": str(e)})

    def get_related_topics(self, topic: str) -> str:
        """
        Return topics reachable via PRECEDED_BY edges.

        Returns:
            JSON array of topic name strings when related topics exist.
            '[]' when none.
            '{"error": "knowledge graph unavailable"}' when unavailable.
        """
        if not self._available:
            return '{"error": "knowledge graph unavailable"}'
        try:
            result = self.conn.execute(
                "MATCH (t1:Topic {name: $topic})-[:PRECEDED_BY*1..3]-(t2:Topic) "
                "WHERE t2.name <> $topic "
                "RETURN DISTINCT t2.name",
                {"topic": topic},
            )
            topics = []
            while result.has_next():
                topics.append(result.get_next()[0])
            return json.dumps(topics)
        except Exception as e:
            logger.warning("KuzuStore.get_related_topics: %s", e)
            return '{"error": "knowledge graph unavailable"}'

    # ── Validation ─────────────────────────────────────────────────────────────

    def _is_valid_graph_claim(self, claim: dict) -> bool:
        """
        Return False for claims that must not be written to the graph.

        Rejects: empty text, markdown headers, LLM refusal phrases, extraction
        failure sentinel, text exceeding 500 chars, multi-paragraph text, or
        no sources attached. Mirrors _is_valid_claim() in provenance.py — the
        gate exists at both the extraction boundary and the graph write boundary
        so contamination is impossible via bypass paths (D042).
        """
        text = (claim.get("claim") or "").strip()
        if not text:
            return False
        if text.startswith("#"):
            return False
        lower = text.lower()
        if any(lower.startswith(p) for p in _REFUSAL_PREFIXES):
            return False
        if "[extraction failed]" in text:
            return False
        if len(text) > 500:
            return False
        if "\n\n" in text:
            return False
        if not claim.get("sources"):
            return False
        return True

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _merge_run(self, run_id: str, started_at: str) -> None:
        self.conn.execute(
            "MERGE (r:Run {run_id: $run_id}) "
            "ON CREATE SET r.started_at = $started_at "
            "ON MATCH SET r.started_at = $started_at",
            {"run_id": run_id, "started_at": started_at},
        )

    def _merge_topic(self, topic: str) -> None:
        self.conn.execute(
            "MERGE (t:Topic {name: $name})",
            {"name": topic},
        )

    def _merge_claim(self, claim_id: str, claim: dict) -> None:
        self.conn.execute(
            "MERGE (c:Claim {claim_id: $claim_id}) "
            "ON CREATE SET c.claim_text = $text, c.confidence = $conf, "
            "c.verification_status = $vstatus, c.evidence_type = $etype, "
            "c.retrieved = $retrieved "
            "ON MATCH SET c.claim_text = $text, c.confidence = $conf, "
            "c.verification_status = $vstatus, c.evidence_type = $etype, "
            "c.retrieved = $retrieved",
            {
                "claim_id": claim_id,
                "text": claim.get("claim", ""),
                "conf": float(claim.get("confidence", 0.5)),
                "vstatus": claim.get("verification_status", "unverified"),
                "etype": claim.get("evidence_type", ""),
                "retrieved": claim.get("timestamp", ""),
            },
        )

    def _merge_source(self, source: dict) -> None:
        url = source.get("url", "")
        if not url:
            return
        try:
            self.conn.execute(
                "MERGE (s:Source {url: $url}) "
                "ON CREATE SET s.title = $title, s.source_type = $stype, "
                "s.retrieved = $retrieved "
                "ON MATCH SET s.title = $title, s.source_type = $stype, "
                "s.retrieved = $retrieved",
                {
                    "url": url,
                    "title": source.get("title", url),
                    "stype": source.get("source_type", "general"),
                    "retrieved": source.get("retrieved", ""),
                },
            )
        except Exception as e:
            logger.debug("KuzuStore._merge_source: %s", e)

    def _create_edge(self, cypher: str, params: dict) -> None:
        """Execute a CREATE edge query, silently ignoring any error (e.g. duplicate)."""
        try:
            self.conn.execute(cypher, params)
        except Exception as e:
            logger.debug("KuzuStore._create_edge: %s", e)

    def _create_temporal_edges(self, topic: str,
                               written: list[tuple[str, dict]]) -> None:
        """Create SUPERSEDES edges: a newer claim supersedes older claims on same topic."""
        for claim_id, claim in written:
            retrieved = claim.get("timestamp", "")
            if not retrieved:
                continue
            try:
                d_new = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            try:
                res = self.conn.execute(
                    "MATCH (c:Claim)-[:BELONGS_TO]->(t:Topic {name: $topic}) "
                    "WHERE c.claim_id <> $cid AND c.retrieved IS NOT NULL "
                    "AND c.retrieved <> '' "
                    "RETURN c.claim_id, c.retrieved",
                    {"topic": topic, "cid": claim_id},
                )
                while res.has_next():
                    row = res.get_next()
                    other_cid, other_retrieved = row[0], row[1]
                    try:
                        d_old = datetime.fromisoformat(
                            other_retrieved.replace("Z", "+00:00")
                        )
                        if d_new > d_old:
                            self._create_edge(
                                "MATCH (a:Claim {claim_id: $a}), (b:Claim {claim_id: $b}) "
                                "CREATE (a)-[:SUPERSEDES]->(b)",
                                {"a": claim_id, "b": other_cid},
                            )
                    except (ValueError, AttributeError):
                        continue
            except Exception as e:
                logger.debug("KuzuStore._create_temporal_edges: %s", e)

    def _create_contradiction_edges(self, topic: str,
                                    written: list[tuple[str, dict]]) -> None:
        """Automatic CONTRADICTS edge creation disabled — edges proposed by Graph Verifier."""
        logger.debug(
            "Automatic CONTRADICTS edge creation disabled — "
            "edges will be proposed by Graph Verifier in a future phase"
        )
        return


def _rejection_reason(claim: dict) -> str:
    """Return a human-readable rejection reason for an invalid claim."""
    text = (claim.get("claim") or "").strip()
    if not text:
        return "empty claim text"
    if text.startswith("#"):
        return "markdown header"
    if "[extraction failed]" in text:
        return "extraction failed sentinel"
    if len(text) > 500:
        return "claim text exceeds 500 characters"
    if "\n\n" in text:
        return "multi-paragraph claim"
    lower = text.lower()
    if any(lower.startswith(p) for p in _REFUSAL_PREFIXES):
        return "LLM refusal phrase"
    if not claim.get("sources"):
        return "no sources attached"
    return "invalid claim"
