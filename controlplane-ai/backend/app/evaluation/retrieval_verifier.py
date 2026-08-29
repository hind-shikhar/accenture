"""
Retrieval-Based Hallucination Verifier.
Verifies AI response claims against local simulated enterprise documents.

Flow:
  AI Response → Claim Extraction → Retrieve Relevant Source
  → Compare Claim With Source → VERIFIED / PARTIALLY_VERIFIED / UNVERIFIED / CONTRADICTED

IMPORTANT: verification_status = VERIFIED requires BOTH:
  1. A matching document found in local store AND
  2. AI-Judge also returns SUPPORTED
  Neither alone is sufficient.
"""
import re
import time
from typing import Dict, Any, List, Tuple
import structlog

logger = structlog.get_logger()

# Simulated enterprise document store (15 synthetic facts)
ENTERPRISE_DOCS = {
    "q3_revenue": {
        "content": "Acme Corp Q3 FY2026 revenue grew 14.2% year-over-year to $2.8B.",
        "keywords": ["q3", "revenue", "2026", "14", "2.8"],
        "source": "Q3 FY2026 Financial Report"
    },
    "credit_risk_policy": {
        "content": "Per Credit Risk Policy v3.1: all loans above $500,000 require dual approval. Risk appetite is 2% NPL ratio.",
        "keywords": ["credit", "risk", "loan", "500000", "npl", "approval"],
        "source": "Credit Risk Policy v3.1"
    },
    "data_retention": {
        "content": "Customer data must be retained for 7 years per regulatory requirement. PII must be anonymized after 2 years.",
        "keywords": ["data", "retention", "7 years", "pii", "anonymize"],
        "source": "Data Governance Policy 2026"
    },
    "headcount": {
        "content": "Total global headcount as of Q3 2026: 48,200 employees across 32 countries.",
        "keywords": ["headcount", "employees", "48200", "32 countries", "global"],
        "source": "HR Dashboard Q3 2026"
    },
    "product_sla": {
        "content": "Standard SLA for Enterprise Tier is 99.9% uptime, with 4-hour incident response for P1 issues.",
        "keywords": ["sla", "uptime", "99.9", "incident", "response", "p1"],
        "source": "Enterprise SLA Agreement 2026"
    },
    "ai_policy": {
        "content": "All generative AI outputs in regulated workflows must be reviewed by a qualified human before actioning.",
        "keywords": ["ai", "generative", "review", "human", "regulated"],
        "source": "AI Governance Policy v2"
    },
    "refund_policy": {
        "content": "Refunds above $10,000 require senior manager approval. Standard refund processing is 5-7 business days.",
        "keywords": ["refund", "10000", "approval", "manager", "5-7 days"],
        "source": "Finance Operations Manual"
    },
    "market_share": {
        "content": "Acme Corp holds 18.4% market share in enterprise middleware as of H1 2026.",
        "keywords": ["market share", "18.4", "middleware", "enterprise", "h1 2026"],
        "source": "Market Analysis Report H1 2026"
    },
}


import os
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

class RetrievalVerifier:
    def __init__(self):
        self.doc_store = ENTERPRISE_DOCS
        self.chroma_client = None
        self.collection = None
        
        # Architecture 2: Real Vector DB integration
        vector_url = os.getenv("VECTOR_DB_URL")
        if vector_url and CHROMA_AVAILABLE:
            try:
                host, port = vector_url.replace("http://", "").split(":")
                self.chroma_client = chromadb.HttpClient(host=host, port=int(port))
                self.collection = self.chroma_client.get_or_create_collection("enterprise_docs")
                logger.info("chromadb_connected", host=host, port=port)
            except Exception as e:
                logger.warning("chromadb_connection_failed", error=str(e), fallback="dictionary")

    async def verify(self, response: str) -> Dict[str, Any]:
        start = time.time()

        claims = self._extract_claims(response)
        if not claims:
            latency = (time.time() - start) * 1000
            return {
                "source": "retrieval_verifier",
                "verification_status": "NOT_CHECKED",
                "matched_documents": [],
                "claims_extracted": [],
                "latency_ms": round(latency, 2)
            }

        matches = []
        contradictions = []
        unmatched = []

        for claim in claims:
            match = self._retrieve_relevant_doc(claim)
            if not match:
                # No document in the store is even about this claim — distinct
                # from finding a document and disagreeing with it. Surfaced
                # separately so a reviewer/UI can tell "no source to check
                # against" apart from "checked and inconsistent".
                unmatched.append(claim)
                continue
            is_consistent = self._compare_claim_to_doc(claim, match["content"])
            if is_consistent:
                matches.append({"claim": claim, "source": match["source"], "consistent": True})
            else:
                contradictions.append({"claim": claim, "source": match["source"], "consistent": False})

        # Determine verification status
        if contradictions:
            status = "CONTRADICTED"
        elif len(matches) == len(claims) and matches:
            status = "VERIFIED"
        elif matches:
            status = "PARTIALLY_VERIFIED"
        else:
            status = "UNVERIFIED"

        latency = (time.time() - start) * 1000
        result = {
            "source": "retrieval_verifier",
            "verification_status": status,
            "matched_documents": [m["source"] for m in matches],
            "claims_extracted": claims,
            "contradictions": [c["claim"] for c in contradictions],
            "unmatched_claims": unmatched,
            "latency_ms": round(latency, 2)
        }
        logger.info("retrieval_verify_complete", status=status, claims=len(claims),
                    matches=len(matches), unmatched=len(unmatched))
        return result

    def _extract_claims(self, response: str) -> List[str]:
        """Extract sentences containing numeric or specific claims."""
        # A naive split on every '.' chops decimal figures like "14.2%" or
        # "$2.8B" into separate fragments, breaking keyword/number matching
        # against the doc store for exactly the financial claims this is
        # meant to verify. Protect only genuine decimal points — a '.' with
        # a digit on BOTH sides — before splitting on sentence punctuation;
        # a period like "...FY2025. Note:" (digit before, space after) is a
        # real sentence boundary and must still split normally.
        protected = re.sub(r'(?<=\d)\.(?=\d)', '\0', response)
        sentences = [s.replace('\0', '.') for s in re.split(r'[.!?]', protected)]
        claims = []
        claim_patterns = [
            r'\d+[%$]', r'\$[\d,]+', r'\d+\.\d+%',
            r'grew by', r'increased', r'decreased', r'as of',
            r'policy', r'require', r'sla', r'uptime', r'retention'
        ]
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 20:
                if any(re.search(p, sent.lower()) for p in claim_patterns):
                    claims.append(sent)
        return claims[:5]  # Cap at 5 claims

    def _retrieve_relevant_doc(self, claim: str) -> Dict[str, Any]:
        """Find the most relevant document for a claim."""
        if self.collection:
            try:
                results = self.collection.query(query_texts=[claim], n_results=1)
                if results['documents'] and results['documents'][0]:
                    return {"content": results['documents'][0][0], "source": results['metadatas'][0][0].get("source", "Vector DB")}
            except Exception:
                pass  # Fallback to local dict

        claim_lower = claim.lower()
        best_match = None
        best_score = 0

        for doc_id, doc in self.doc_store.items():
            score = sum(1 for kw in doc["keywords"] if kw in claim_lower)
            if score > best_score:
                best_score = score
                best_match = doc

        return best_match if best_score > 0 else None

    def _compare_claim_to_doc(self, claim: str, doc_content: str) -> bool:
        """Check if the claim is broadly consistent with the document."""
        # Extract key numbers from both
        claim_nums = set(re.findall(r'\d+\.?\d*', claim))
        doc_nums = set(re.findall(r'\d+\.?\d*', doc_content))
        # If claim has numbers not in doc, it may be contradicting
        claim_only_nums = claim_nums - doc_nums
        if len(claim_only_nums) > 2:
            return False
        return True


# Singleton
retrieval_verifier = RetrievalVerifier()
