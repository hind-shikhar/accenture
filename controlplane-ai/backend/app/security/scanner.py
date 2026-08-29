import re
import asyncio
from typing import Set, Tuple
from backend.app.schemas.chat import SecurityResult
from backend.app.security.injection_patterns import score_injection
import structlog

logger = structlog.get_logger()

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("Presidio ML libraries not found. Falling back to heuristics.")


class SecurityScanner:
    def __init__(self):
        self.ml_enabled = ML_AVAILABLE

        if self.ml_enabled:
            logger.info("Initializing Microsoft Presidio ML models for SecurityScanner...")
            try:
                self.analyzer = AnalyzerEngine(supported_languages=["en"])
                self.anonymizer = AnonymizerEngine()
                logger.info("Presidio loaded successfully.")
            except Exception as e:
                logger.warning(f"Could not load Presidio: {e}. Falling back to heuristics.")
                self.ml_enabled = False

        # Fallback heuristic regex patterns
        self.pii_patterns = {
            "EMAIL":       r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
            "PHONE":       r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
            "SSN":         r"\b\d{3}-\d{2}-\d{4}\b",
            "CREDIT_CARD": r"\b(?:\d[ -]?){13,16}\b",
            "IP_ADDRESS":  r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        }
        # Credential/secret keyword detection (always run — regex, not Presidio)
        self.credential_keywords = [
            "password", "passwd", "my password is", "secret", "api key",
            "api_key", "access token", "private key", "credentials",
            "passphrase", "my pin", "otp is", "secret code", "auth token"
        ]
        if not self.ml_enabled:
            logger.info("Heuristic Security Scanner Ready.")

    # ── Synchronous helper (runs in thread pool) ────────────────────────────────
    def _presidio_scan(self, text: str) -> Tuple[str, Set[str]]:
        """CPU-bound Presidio NLP call. Must be called via run_in_executor."""
        results = self.analyzer.analyze(text=text, language="en")
        pii_types: Set[str] = set()
        masked = text
        if results:
            for r in results:
                pii_types.add(r.entity_type)
            anon = self.anonymizer.anonymize(text=text, analyzer_results=results)
            masked = anon.text
        return masked, pii_types

    # ── Public async interface ──────────────────────────────────────────────────
    async def scan_input(self, text: str) -> Tuple[str, SecurityResult]:
        pii_types: Set[str] = set()
        masked_text = text
        text_lower = text.lower()

        # 1. PII detection — offload to thread pool so we don't block the event loop
        if self.ml_enabled:
            try:
                loop = asyncio.get_event_loop()
                masked_text, pii_types = await loop.run_in_executor(
                    None, self._presidio_scan, text
                )
            except Exception as e:
                logger.warning(f"Presidio scan error: {e}. Using regex fallback.")
                masked_text, pii_types = self._regex_scan(text)
        else:
            masked_text, pii_types = self._regex_scan(text)

        # 2. Credential keyword detection (always — instant regex)
        cred_hits = [kw for kw in self.credential_keywords if kw in text_lower]
        if cred_hits:
            pii_types.add("CREDENTIAL")
            for kw in cred_hits:
                masked_text = re.sub(
                    rf"({re.escape(kw)})\s*(?:is\s*)?(\S+)",
                    r"\1 [CREDENTIAL_REDACTED]",
                    masked_text,
                    flags=re.IGNORECASE
                )

        # 3. Injection scoring (regex pattern families — instant, see injection_patterns.py)
        injection_score, injection_categories = score_injection(text)

        # 4. Build risk level and actions
        actions = []
        if pii_types:
            actions.append("MASK_PII")

        is_allowed = injection_score < 0.7
        risk_level = "low"

        if injection_score >= 0.7:
            risk_level = "high"
            actions.append("BLOCK_INJECTION")
        elif "CREDENTIAL" in pii_types:
            risk_level = "high"
            actions.append("FLAG_CREDENTIAL")
        elif pii_types or injection_score > 0.3:
            risk_level = "medium"

        logger.info("security_scan_complete",
                    pii_types=list(pii_types),
                    injection_score=injection_score,
                    injection_categories=injection_categories,
                    risk_level=risk_level,
                    ml_used=self.ml_enabled)

        return masked_text, SecurityResult(
            allowed=is_allowed,
            risk_level=risk_level,
            pii_detected=len(pii_types) > 0,
            pii_types=list(pii_types),
            prompt_injection_score=injection_score,
            actions=actions
        )

    def _regex_scan(self, text: str) -> Tuple[str, Set[str]]:
        """Fast regex PII fallback."""
        pii_types: Set[str] = set()
        masked = text
        for pii_type, pattern in self.pii_patterns.items():
            if re.search(pattern, masked):
                pii_types.add(pii_type)
                masked = re.sub(pattern, f"[{pii_type}_REDACTED]", masked)
        return masked, pii_types
