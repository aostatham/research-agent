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
  classify_source_type()     — classify a URL into government/academic/news/general
"""

import json
import os
import re
import warnings
from datetime import datetime, timezone

from evidence.schema import EvidenceSource, EvidenceClaim, ProvenanceReport


def _strip_code_fence(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from an LLM response."""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]  # drop opening fence line (```json, ```, etc.)
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


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
        schema_version="1.0",
        report_file=os.path.basename(output_path),
        generated=datetime.now(timezone.utc).isoformat(),
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
      coverage          — verified_claims / total_claims (0.0 if no claims)
      confidence        — mean of all claim confidence scores (0.0 if no claims)
      contradictions    — total count across all claims
      verified_claims   — count where verification_status == "verified"
      unverified_claims — count where verification_status == "unverified"
      disputed_claims   — count where verification_status == "disputed"
    """
    if not claims:
        return {
            "coverage": 0.0,
            "confidence": 0.0,
            "contradictions": 0,
            "verified_claims": 0,
            "unverified_claims": 0,
            "disputed_claims": 0,
        }

    verified = sum(1 for c in claims if c["verification_status"] == "verified")
    unverified = sum(1 for c in claims if c["verification_status"] == "unverified")
    disputed = sum(1 for c in claims if c["verification_status"] == "disputed")
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
        "disputed_claims": disputed,
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

    Returns one of: government | academic | news | reference |
                    institutional | industry | video | forum | general

    Maintenance guide for layer 3 (hardcoded list):
      ADD a domain to layer 3 when:
        - It appears in 3+ research runs misclassified as general
        - It is a well-known authoritative source
        - LLM fallback is unavailable or gives incorrect results for it
      DO NOT add speculatively — only add on evidence of misclassification
      DO NOT add domains that match existing TLD or stable patterns
      industry type has no hardcoded list — too numerous and volatile;
        use config.yaml source_classification for project-specific industry domains

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

    stable_video = ["youtube.com", "youtu.be", "vimeo.com"]
    if any(m in u for m in stable_video):
        return "video"

    stable_forum = ["reddit.com", "quora.com", "stackoverflow.com",
                    "stackexchange.com", "discourse."]
    if any(m in u for m in stable_forum):
        return "forum"

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

    # Think tanks, policy institutes, NGOs, and industry associations
    # without government or academic TLD conventions
    institutional_institutional = [
        "weforum.org", "rand.org", "chathamhouse.org", "cfr.org",
        "piie.com", "oxfordenergy.org", "belfercenter.org",
        "wilsoncenter.org", "carnegieendowment.org",
        "fusionindustryassociation.org", "world-nuclear.org",
        "nuclearenergyinstitute.org", "ans.org",
        "energyintel.com", "spglobal.com", "woodmac.com",
    ]
    if any(m in u for m in institutional_institutional):
        return "institutional"

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
            "Choose from: government, academic, news, reference, "
            "institutional, industry, video, forum, general\n"
            "government = official government body or intergovernmental organisation\n"
            "academic = peer-reviewed journal, university research, conference proceedings\n"
            "news = established news publication or science news outlet\n"
            "reference = encyclopaedia or general reference resource\n"
            "institutional = think tank, policy institute, NGO, industry association\n"
            "industry = company site, startup, commercial organisation\n"
            "video = YouTube, Vimeo, or other video platform\n"
            "forum = Reddit, Quora, Stack Exchange, or discussion site\n"
            "general = personal blog, unclassified site\n"
            "Return only the single word. No explanation."
        )
        try:
            response = llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            result = (response.content or "").strip().lower()
            valid = {"government", "academic", "news", "reference",
                     "institutional", "industry", "video", "forum", "general"}
            if result in valid:
                return result
        except (AttributeError, ConnectionError, TimeoutError,
                json.JSONDecodeError, ValueError) as e:
            warnings.warn(f"LLM source classification failed: {e}", stacklevel=2)

    return "general"


def score_confidence(sources: list) -> float:
    """
    Score confidence for a claim based on its sources.

    Scoring rules:
      Base score:                             0.40
      Per government source:                 +0.15 (max +0.30)
      Per academic source:                   +0.12 (max +0.24)
      Per news source:                       +0.06 (max +0.12)
      Per reference source:                  +0.03 (max +0.06)
      Per institutional source:              +0.08 (max +0.16)
      Per industry source:                   +0.02 (max +0.04)
      Per video source:                      +0.01 (max +0.02)
      Per forum source:                      +0.00
      Per general source:                    +0.00
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
        "government":   (0.15, 0.30),
        "academic":     (0.12, 0.24),
        "news":         (0.06, 0.12),
        "reference":    (0.03, 0.06),
        "institutional": (0.08, 0.16),
        "industry":     (0.02, 0.04),
        "video":        (0.01, 0.02),
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
    topic: str,
    answer: str,
    sources: list,
    llm_client,
    claim_id_start: int = 1,
    custom_domains: dict = None,
    verification: str = "unverified"
) -> list:
    """
    Use an LLM to extract atomic claims from a research answer.

    Each claim is a single verifiable fact extracted from the answer text
    that is directly about the research topic — tangential mentions,
    comparisons, and asides are excluded.

    If JSON parsing of the LLM response fails, falls back to a single
    placeholder claim using the first 200 characters of the answer.

    Args:
        question:       The research question that produced this answer
        topic:          The overarching research topic; used to anchor
                        the relevance constraint in the extraction prompt
        answer:         The full answer text
        sources:        List of {"title": str, "url": str} source dicts
        llm_client:     LLMClient instance for extraction
        claim_id_start: Starting ID for claim numbering
        custom_domains: Optional dict from config source_classification
        verification:   ResearchResult.verification value — "verified",
                        "refuted", or "unverified". "refuted" maps to
                        verification_status="disputed" on the claim.

    Returns:
        List of EvidenceClaim TypedDicts
    """
    now = datetime.now(timezone.utc).isoformat()

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
        f"Research topic: {topic}\n\n"
        f"Question: {question}\n\n"
        f"Answer: {answer}\n\n"
        "Extract only claims that are directly about the research topic "
        "and directly supported by this answer.\n\n"
        "Each claim must be:\n"
        "- A single sentence stating one verifiable fact\n"
        "- Directly about the research topic, not about tangential "
        "comparisons, analogies, or unrelated subjects mentioned in passing\n"
        "- Directly supported by the answer text — do not infer or extrapolate\n"
        "- Not combined with other facts\n\n"
        "Extract between 1 and 8 claims. If the answer contains fewer than "
        "3 facts directly about the research topic, extract only those that "
        "qualify. Do not pad with tangential or low-confidence facts.\n\n"
        'Return ONLY a JSON array of strings. No preamble, no explanation.\n'
        'Example: ["Claim one.", "Claim two.", "Claim three."]'
    )

    try:
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        raw = _strip_code_fence(response.content or "[]")
        claim_texts = json.loads(raw)
        if not isinstance(claim_texts, list) or not claim_texts:
            raise ValueError("empty or non-list response")
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        warnings.warn(f"Claim extraction failed, using fallback: {e}", stacklevel=2)
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
            verification_status=(
                "verified" if verification == "verified"
                else "disputed" if verification == "refuted"
                else "unverified"
            ),
            timestamp=now,
            sources=deduped_sources,
            report_line=None,
            synthesis_status="not_attempted",
        )
        claims.append(claim)

    return claims


def build_claims_from_results(
    research_results: list,
    llm_client,
    topic: str = "",
    custom_domains: dict = None
) -> list:
    """
    Build EvidenceClaim objects from a list of ResearchResult objects.

    Calls extract_claims_from_answer() for each ResearchResult and assigns
    sequential IDs across all questions. Returns a flat list of all
    EvidenceClaim objects.

    Args:
        research_results: list[ResearchResult] from orchestrator._last_research_results
        llm_client:       LLMClient instance passed to extract_claims_from_answer()
        topic:            The overarching research topic; passed to
                          extract_claims_from_answer() for relevance anchoring
        custom_domains:   Optional dict from config source_classification

    Returns:
        Flat list of EvidenceClaim TypedDicts
    """
    all_claims = []
    next_id = 1

    for rr in research_results:
        new_claims = extract_claims_from_answer(
            question=rr.question,
            topic=topic,
            answer=rr.answer,
            sources=rr.sources,
            llm_client=llm_client,
            claim_id_start=next_id,
            custom_domains=custom_domains,
            verification=rr.verification,
        )
        all_claims.extend(new_claims)
        next_id += len(new_claims)

    return all_claims


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "of", "in", "on", "at", "to",
    "for", "with", "by", "from", "and", "or", "but", "not", "this",
    "that", "these", "those", "it", "its",
})

_PUNCT = str.maketrans("", "", ".,;:!?\"'()")


def _extract_key_phrase(claim: str) -> str | None:
    """Return the longest run of 2+ consecutive capitalised words in claim, or None."""
    words = claim.split()
    best: list[str] = []
    current: list[str] = []
    for word in words:
        clean = word.translate(_PUNCT)
        if clean and clean[0].isupper():
            current.append(clean)
        else:
            if len(current) >= 2 and len(current) > len(best):
                best = current[:]
            current = []
    if len(current) >= 2 and len(current) > len(best):
        best = current
    return " ".join(best) if best else None


def _content_words(text: str) -> set[str]:
    """Return lowercase non-stopword tokens from text."""
    result: set[str] = set()
    for word in text.split():
        w = word.lower().translate(_PUNCT)
        if w and w not in _STOPWORDS:
            result.add(w)
    return result


def annotate_report_lines(report: str, claims: list) -> tuple:
    """
    Add inline footnote markers to report text and record line numbers.

    For each claim, tries three matching tiers in order, stopping at the
    first match:

      Tier 1 — key phrase: longest run of 2+ consecutive capitalised words
        in the claim searched case-insensitively against each report line.
        Catches proper nouns and named entities the synthesiser preserves
        verbatim (e.g. "National Ignition Facility", "December 2022").

      Tier 2 — number/date: all digit sequences from the claim must appear
        in the candidate line, and the line must also share at least 3
        content words with the claim.

      Tier 3 — content word overlap: a line sharing 5 or more non-stopword
        tokens with the claim is a candidate; the highest-overlap line wins.

    When a match is found:
      - Inserts [N] after the end of that line in the report
      - Sets report_line on the claim to the matched line number (1-based)
      - Sets synthesis_status="anchored" (Tier 1) or "paraphrased" (Tier 2/3)

    Only annotates where a clear match exists. Does not force markers.
    Each line is only annotated once (first matching claim wins).

    Args:
        report: Full report text
        claims: List of EvidenceClaim dicts (mutated in place for report_line)

    Returns:
        (annotated_report: str, claims_with_lines: list)
    """
    # Only annotate prose — markers must not land in the References section
    ref_marker = "\n## References"
    if ref_marker in report:
        prose, references = report.split(ref_marker, 1)
    else:
        prose, references = report, None

    lines = prose.split("\n")
    annotated_lines = list(lines)
    annotated_line_indices: set = set()

    for claim in claims:
        claim_text = claim["claim"]
        if not claim_text:
            continue

        match_idx = None
        matched_tier = None

        # Tier 1 — key phrase (longest 2+ capitalised-word run)
        key_phrase = _extract_key_phrase(claim_text)
        if key_phrase:
            kp_lower = key_phrase.lower()
            for line_idx, line in enumerate(lines):
                if line_idx in annotated_line_indices:
                    continue
                if kp_lower in line.lower():
                    match_idx = line_idx
                    matched_tier = 1
                    break

        # Tier 2 — number/date match
        if match_idx is None:
            digits = re.findall(r'\d+', claim_text)
            if digits:
                claim_words = _content_words(claim_text)
                best_overlap = -1
                best_line_idx = None
                for line_idx, line in enumerate(lines):
                    if line_idx in annotated_line_indices:
                        continue
                    if all(d in line for d in digits):
                        overlap = len(claim_words & _content_words(line))
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_line_idx = line_idx
                if best_line_idx is not None and best_overlap >= 3:
                    match_idx = best_line_idx
                    matched_tier = 2

        # Tier 3 — content word overlap (minimum 5 shared words)
        if match_idx is None:
            claim_words = _content_words(claim_text)
            best_overlap = -1
            best_line_idx = None
            for line_idx, line in enumerate(lines):
                if line_idx in annotated_line_indices:
                    continue
                overlap = len(claim_words & _content_words(line))
                if overlap >= 5 and overlap > best_overlap:
                    best_overlap = overlap
                    best_line_idx = line_idx
            if best_line_idx is not None:
                match_idx = best_line_idx
                matched_tier = 3

        if match_idx is not None:
            marker = f" [{claim['id']}]"
            annotated_lines[match_idx] = annotated_lines[match_idx] + marker
            claim["report_line"] = match_idx + 1  # 1-based
            claim["synthesis_status"] = "anchored" if matched_tier == 1 else "paraphrased"
            annotated_line_indices.add(match_idx)

    annotated_prose = "\n".join(annotated_lines)
    if references is not None:
        return annotated_prose + ref_marker + references, claims
    return annotated_prose, claims


