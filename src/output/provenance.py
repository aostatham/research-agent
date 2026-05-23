"""
Provenance file generation for the research-agent pipeline.

Writes a .provenance.json file alongside each report, recording the
claims made, their sources, confidence scores, and quality metrics.

In Part 1, claims are placeholder objects built directly from raw
research results. Full claim extraction and confidence scoring
arrive in Part 2.

Public API:
  write_provenance_file()    — write .provenance.json next to the report
  build_quality_metrics()    — compute aggregate metrics from a claims list
  classify_source_type()     — classify a URL into government/academic/news/blog
  build_placeholder_claims() — build minimal claims from raw results/sources
"""

import json
import os
from datetime import datetime

from evidence.schema import EvidenceSource, EvidenceClaim, ProvenanceReport


def write_provenance_file(
    output_path: str,
    claims: list,
    quality_metrics: dict
) -> str:
    """
    Write a .provenance.json file alongside the report.

    Derives the provenance path by replacing the report extension:
      output/nuclear_fusion.md -> output/nuclear_fusion.provenance.json

    Args:
        output_path:     Path to the saved report file (any extension)
        claims:          List of EvidenceClaim dicts
        quality_metrics: Dict from build_quality_metrics()

    Returns:
        Path to the written provenance file
    """
    base = os.path.splitext(output_path)[0]
    prov_path = f"{base}.provenance.json"

    os.makedirs(os.path.dirname(prov_path) or ".", exist_ok=True)

    report = ProvenanceReport(
        report_file=os.path.basename(output_path),
        generated=datetime.utcnow().isoformat(),
        quality_metrics=quality_metrics,
        claims=claims
    )

    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return prov_path


def build_quality_metrics(claims: list) -> dict:
    """
    Compute quality metrics from a list of EvidenceClaim objects.

    Returns a dict with:
      coverage         — verified_claims / total_claims (0.0 if no claims)
      confidence       — mean of all claim confidence scores (0.0 if no claims)
      contradictions   — total count across all claims
      verified_claims  — count where verification_status == "verified"
      unverified_claims — count where verification_status == "unverified"
    """
    if not claims:
        return {
            "coverage": 0.0,
            "confidence": 0.0,
            "contradictions": 0,
            "verified_claims": 0,
            "unverified_claims": 0,
        }

    verified = sum(1 for c in claims if c["verification_status"] == "verified")
    unverified = sum(1 for c in claims if c["verification_status"] == "unverified")
    total = len(claims)
    contradictions = sum(len(c["contradictions"]) for c in claims)
    confidence = sum(c["confidence"] for c in claims) / total
    coverage = verified / total

    return {
        "coverage": coverage,
        "confidence": confidence,
        "contradictions": contradictions,
        "verified_claims": verified,
        "unverified_claims": unverified,
    }


def classify_source_type(
    url: str,
    llm_client=None,
    custom_domains: dict = None
) -> str:
    """
    Classify a URL into a source type using five ordered layers.
    First match wins.

    Layers:
      1. TLD patterns      — .gov, .edu, .mil, .gov.uk, .gov.au etc
      2. Stable patterns   — arxiv.org, pubmed.ncbi, doi.org, wikipedia,
                             britannica.com
      3. Hardcoded list    — high-value institutional domains that do not
                             follow TLD conventions (see below)
      4. Custom domains    — user-supplied via config.yaml
                             source_classification:
                               academic: [mycustomjournal.org]
                               government: [specialagency.int]
      5. LLM fallback      — only called when llm_client is provided
                             and layers 1-4 produce no match

    Returns one of: government | academic | news | blog | reference

    Maintenance guide for layer 3 (hardcoded list):
      ADD a domain to layer 3 when:
        - It appears in 3+ research runs misclassified as blog
        - It is a well-known authoritative source
        - LLM fallback is unavailable or gives incorrect results for it
      DO NOT add speculatively — only add on evidence of misclassification
      DO NOT add domains that match existing TLD or stable patterns

    Args:
        url:            URL string to classify
        llm_client:     Optional LLMClient instance for fallback
        custom_domains: Dict from config source_classification section
                        {"academic": [...], "government": [...], ...}
                        None is handled gracefully

    Returns:
        Source type string
    """
    u = url.lower()

    # pubmed.ncbi must be checked before the .gov TLD since the canonical
    # PubMed URL (pubmed.ncbi.nlm.nih.gov) contains .gov but is academic.
    if "pubmed.ncbi" in u:
        return "academic"

    # Layer 1 — TLD patterns (most reliable, zero maintenance)
    gov_tlds = [
        ".gov", ".mil",
        ".gov.uk", ".gov.au", ".gov.ca", ".gov.ie", ".gov.nz",
        ".gov.sg", ".gov.in", ".gc.ca", ".govt.nz",
    ]
    if any(p in u for p in gov_tlds):
        return "government"

    academic_tlds = [".edu", ".ac.uk", ".ac.nz", ".ac.za", ".ac.jp"]
    if any(p in u for p in academic_tlds):
        return "academic"

    # Layer 2 — stable subdomain/path patterns (narrow, high-confidence)
    stable_academic = ["arxiv.org", "pubmed.ncbi", "doi.org", "ssrn.com",
                       "jstor.org", "repec.org"]
    if any(m in u for m in stable_academic):
        return "academic"

    stable_reference = ["wikipedia.org", "britannica.com", "encyclopedia.com"]
    if any(m in u for m in stable_reference):
        return "reference"

    # Layer 3 — hardcoded institutional domains
    # Only domains confirmed misclassified in 3+ real research runs.

    # Intergovernmental and national-level organisations without .gov TLD
    institutional_government = [
        "iaea.org", "iter.org", "euro-fusion.org", "cern.ch",
        "who.int", "un.org", "worldbank.org", "imf.org",
        "ec.europa.eu", "europa.eu", "oecd.org", "iea.org",
    ]
    if any(m in u for m in institutional_government):
        return "government"

    # Peer-reviewed publishers, preprint servers, and research databases
    institutional_academic = [
        "frontiersin.org", "epj-conferences.org", "fz-juelich.de",
        "sciencedirect.com", "springer.com", "wiley.com",
        "tandfonline.com", "researchgate.net", "semanticscholar.org",
        "plos.org", "cell.com", "thelancet.com", "bmj.com", "nejm.org",
        "ieee.org", "acm.org", "aps.org", "iop.org", "rsc.org",
        "acs.org", "mdpi.com", "f1000research.com", "biorxiv.org",
        "medrxiv.org", "chemrxiv.org", "psyarxiv.com",
    ]
    if any(m in u for m in institutional_academic):
        return "academic"

    # Established news publications and science news outlets
    institutional_news = [
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
        "theguardian.com", "nytimes.com", "washingtonpost.com",
        "wsj.com", "ft.com", "economist.com", "bloomberg.com",
        "forbes.com", "wired.com", "techcrunch.com", "arstechnica.com",
        "newscientist.com", "scientificamerican.com",
        "technologyreview.com", "nature.com/news",
        "science.org/news", "phys.org", "sciencedaily.com",
        "nucnet.org", "world-nuclear-news.org",
    ]
    if any(m in u for m in institutional_news):
        return "news"

    # Layer 4 — custom domains from config.yaml source_classification
    if custom_domains:
        for source_type, domains in custom_domains.items():
            if isinstance(domains, list) and any(d in u for d in domains):
                return source_type

    # Layer 5 — LLM fallback (only when no pattern matched)
    if llm_client is not None:
        prompt = (
            "Classify this URL into exactly one source type.\n"
            f"URL: {url}\n"
            "Choose from: government, academic, news, blog, reference\n"
            "government = official government body or intergovernmental organisation\n"
            "academic = peer-reviewed journal, university research, conference proceedings\n"
            "news = established news publication or science news outlet\n"
            "reference = encyclopaedia or general reference resource\n"
            "blog = everything else including industry sites, company pages, forums\n"
            "Return only the single word. No explanation."
        )
        try:
            response = llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            result = (response.content or "").strip().lower()
            if result in ("government", "academic", "news", "reference", "blog"):
                return result
        except Exception:
            pass

    return "blog"


def score_confidence(sources: list) -> float:
    """
    Score confidence for a claim based on its sources.

    Scoring rules:
      Base score:                             0.40
      Per government source:                 +0.15 (max +0.30)
      Per academic source:                   +0.12 (max +0.24)
      Per news source:                       +0.06 (max +0.12)
      Per reference source:                  +0.03 (max +0.06)
      Corroboration bonus (2 sources):       +0.05
      Corroboration bonus (3+ sources):      +0.10
      Cap:                                    1.00

    Args:
        sources: List of EvidenceSource dicts with source_type field

    Returns:
        Float between 0.0 and 1.0
    """
    score = 0.40

    type_bonuses = {
        "government": (0.15, 0.30),
        "academic":   (0.12, 0.24),
        "news":       (0.06, 0.12),
        "reference":  (0.03, 0.06),
    }

    for stype, (per_source, cap) in type_bonuses.items():
        count = sum(1 for s in sources if s.get("source_type") == stype)
        score += min(count * per_source, cap)

    if len(sources) >= 3:
        score += 0.10
    elif len(sources) == 2:
        score += 0.05

    return min(score, 1.0)


def extract_claims_from_answer(
    question: str,
    answer: str,
    sources: list,
    llm_client,
    claim_id_start: int = 1,
    custom_domains: dict = None
) -> list:
    """
    Use an LLM to extract atomic claims from a research answer.

    Each claim is a single verifiable fact extracted from the answer text.
    Returns a list of EvidenceClaim objects.

    If JSON parsing of the LLM response fails, falls back to a single
    placeholder claim using the first 200 characters of the answer.

    Args:
        question:       The research question that produced this answer
        answer:         The full answer text
        sources:        List of {"title": str, "url": str} source dicts
        llm_client:     LLMClient instance for extraction
        claim_id_start: Starting ID for claim numbering
        custom_domains: Optional dict from config source_classification

    Returns:
        List of EvidenceClaim TypedDicts
    """
    now = datetime.utcnow().isoformat()

    evidence_sources = [
        EvidenceSource(
            title=s.get("title", ""),
            url=s.get("url", ""),
            source_type=classify_source_type(
                s.get("url", ""), custom_domains=custom_domains
            ),
            retrieved=now,
        )
        for s in sources
    ]

    primary_url = sources[0]["url"] if sources else ""

    prompt = (
        "You are extracting atomic factual claims from a research answer.\n\n"
        f"Question: {question}\n\n"
        f"Answer: {answer}\n\n"
        "Extract 3 to 8 atomic claims from this answer.\n"
        "Each claim must be:\n"
        "- A single sentence stating one verifiable fact\n"
        "- Directly supported by the answer text\n"
        "- Not combined with other facts\n\n"
        'Return ONLY a JSON array of strings. No preamble, no explanation.\n'
        'Example: ["Claim one.", "Claim two.", "Claim three."]'
    )

    try:
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        raw = response.content.strip() if response.content else "[]"
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        claim_texts = json.loads(raw)
        if not isinstance(claim_texts, list) or not claim_texts:
            raise ValueError("empty or non-list response")
    except Exception:
        fallback_text = answer[:200] + (" [extraction failed]" if len(answer) > 200 else "")
        claim_texts = [fallback_text]

    seen_urls: set = set()
    deduped_sources = []
    for source in evidence_sources:
        if source["url"] not in seen_urls:
            seen_urls.add(source["url"])
            deduped_sources.append(source)

    claims = []
    for i, text in enumerate(claim_texts):
        claim = EvidenceClaim(
            id=claim_id_start + i,
            claim=str(text),
            source=primary_url,
            confidence=score_confidence(deduped_sources),
            contradictions=[],
            evidence_type="qualitative",
            verification_status="unverified",
            timestamp=now,
            sources=deduped_sources,
            report_line=None,
        )
        claims.append(claim)

    return claims


def build_claims_from_results(
    results: dict,
    sources: dict,
    llm_client,
    custom_domains: dict = None
) -> list:
    """
    Build EvidenceClaim objects from orchestrator results and sources.

    Calls extract_claims_from_answer() for each question/answer pair and
    assigns sequential IDs across all questions. Returns a flat list of all
    EvidenceClaim objects.

    Args:
        results:        {question: answer} dict from orchestrator.run()
        sources:        {question: [{"title": str, "url": str}]} from orchestrator.run()
        llm_client:     LLMClient instance passed to extract_claims_from_answer()
        custom_domains: Optional dict from config source_classification

    Returns:
        Flat list of EvidenceClaim TypedDicts
    """
    all_claims = []
    next_id = 1

    for question, answer in results.items():
        question_sources = sources.get(question, [])
        new_claims = extract_claims_from_answer(
            question=question,
            answer=answer,
            sources=question_sources,
            llm_client=llm_client,
            claim_id_start=next_id,
            custom_domains=custom_domains,
        )
        all_claims.extend(new_claims)
        next_id += len(new_claims)

    return all_claims


def annotate_report_lines(report: str, claims: list) -> tuple:
    """
    Add inline footnote markers to report text and record line numbers.

    For each claim, searches the report for the first 8 words of the claim
    (case-insensitive substring match). When found:
      - Inserts [N] after the end of that line in the report
      - Sets report_line on the claim to the matched line number (1-based)

    Only annotates where a clear match exists. Does not force markers.
    Each line is only annotated once (first matching claim wins).

    Args:
        report: Full report text
        claims: List of EvidenceClaim dicts (mutated in place for report_line)

    Returns:
        (annotated_report: str, claims_with_lines: list)
    """
    lines = report.split("\n")
    annotated_lines = list(lines)
    annotated_line_indices: set = set()

    for claim in claims:
        words = claim["claim"].split()
        phrase = " ".join(words[:8]).lower()
        if not phrase:
            continue

        for line_idx, line in enumerate(lines):
            if line_idx in annotated_line_indices:
                continue
            if phrase in line.lower():
                marker = f" [{claim['id']}]"
                annotated_lines[line_idx] = annotated_lines[line_idx] + marker
                claim["report_line"] = line_idx + 1  # 1-based
                annotated_line_indices.add(line_idx)
                break

    return "\n".join(annotated_lines), claims


def build_placeholder_claims(results: dict, sources: dict) -> list:
    """
    Build minimal EvidenceClaim objects from existing results and sources.

    Used in Part 1 before full claim extraction is implemented.
    Each question/answer pair becomes one placeholder claim.

    Defaults:
      confidence          = 0.5  (unscored)
      verification_status = "unverified"
      evidence_type       = "qualitative"
      report_line         = None

    Args:
        results: {question: answer} dict from orchestrator.run()
        sources: {question: [{"title": str, "url": str}]} from orchestrator.run()

    Returns:
        List of EvidenceClaim dicts (one per question)
    """
    now = datetime.utcnow().isoformat()
    claims = []

    for i, (question, answer) in enumerate(results.items(), start=1):
        question_sources = sources.get(question, [])
        primary_url = question_sources[0]["url"] if question_sources else ""

        evidence_sources = [
            EvidenceSource(
                title=s.get("title", ""),
                url=s.get("url", ""),
                source_type=classify_source_type(s.get("url", "")),
                retrieved=now,
            )
            for s in question_sources
        ]

        claim = EvidenceClaim(
            id=i,
            claim=answer,
            source=primary_url,
            confidence=0.5,
            contradictions=[],
            evidence_type="qualitative",
            verification_status="unverified",
            timestamp=now,
            sources=evidence_sources,
            report_line=None,
        )
        claims.append(claim)

    return claims
