"""
Mock LLM Provider — Realistic Canned Responses for Demo Mode.
Responses are keyed to common enterprise prompts and matched by keywords.
The mock provider simulates a real LLM without requiring any API key.
"""
import asyncio
import re
from typing import Any, Dict, AsyncGenerator
from backend.app.providers.base import ModelProvider


# Realistic enterprise responses keyed by scenario
CANNED_RESPONSES = [
    {
        "keywords": ["bias", "biased", "stereotype", "generalize"],
        "response": (
            "It is well known that younger employees clearly lack the dedication of older generations, "
            "and obviously people from that specific background are never good at technical roles. "
            "They always struggle with complex tasks."
        )
    },
    {
        "keywords": ["q3", "revenue", "growth", "european", "european market"],
        "response": (
            "Q3 FY2026 revenue in the European market grew 14.2% year-over-year, reaching $2.8B. "
            "Key drivers included strong performance in the DACH region (+18.4%) and expansion of "
            "the enterprise middleware segment. Operating margin improved to 22.1%, up from 19.3% "
            "in Q3 FY2025. Note: figures are subject to final audit confirmation."
        )
    },
    {
        "keywords": ["credit risk", "loan", "approval", "dual approval"],
        "response": (
            "Per Credit Risk Policy v3.1, all loans above $500,000 require dual approval from a "
            "Senior Risk Officer and the Regional Credit Committee. The current risk appetite is "
            "a 2% Non-Performing Loan (NPL) ratio. Loans below $50,000 may be approved by a "
            "single branch manager using the automated credit scoring system."
        )
    },
    {
        "keywords": ["remote work", "work from home", "hybrid policy", "office policy"],
        "response": (
            "The company's hybrid work policy allows employees to work remotely up to 3 days per "
            "week with manager approval. All remote work arrangements must be documented in the "
            "HR portal. Employees are expected to be available during core hours of 10am–3pm in "
            "their local timezone. Exceptions for fully remote roles require VP-level approval "
            "and are reviewed quarterly."
        )
    },
    {
        "keywords": ["refund", "customer refund", "return policy"],
        "response": (
            "Refunds above $10,000 require senior manager approval before processing. Standard "
            "customer refund processing takes 5–7 business days to appear on the original payment "
            "method. For enterprise accounts with active SLAs, expedited refunds can be processed "
            "within 48 hours upon request through the enterprise support portal."
        )
    },
    {
        "keywords": ["data retention", "gdpr", "pii", "anonymize", "customer data"],
        "response": (
            "Per our Data Governance Policy 2026 and GDPR obligations, customer data must be "
            "retained for a minimum of 7 years for regulatory compliance. Personally Identifiable "
            "Information (PII) must be anonymized or pseudonymized after 2 years of inactivity. "
            "Deletion requests under GDPR Article 17 must be processed within 30 days and logged "
            "in the compliance audit trail."
        )
    },
    {
        "keywords": ["sla", "uptime", "incident", "p1", "service level"],
        "response": (
            "The Enterprise Tier SLA guarantees 99.9% monthly uptime, which equates to a maximum "
            "of 8.7 hours downtime per year. P1 incidents (full service outage) require a response "
            "within 15 minutes and resolution or workaround within 4 hours. Customers are entitled "
            "to service credits of 10% of monthly fees for each hour of downtime beyond the SLA "
            "threshold, capped at 30% per month."
        )
    },
    {
        "keywords": ["market share", "competitor", "middleware", "enterprise segment"],
        "response": (
            "Acme Corp holds an 18.4% market share in the enterprise middleware segment as of H1 "
            "2026, making it the second-largest player behind TechGiant Inc. (23.1%). Key "
            "competitive differentiators include our proprietary governance layer, which reduces "
            "compliance overhead by an estimated 40%, and our 99.9% uptime SLA."
        )
    },
    {
        "keywords": ["headcount", "employees", "hiring", "workforce", "staffing"],
        "response": (
            "Total global headcount as of Q3 2026 is 48,200 employees across 32 countries. "
            "The engineering division grew by 12% YoY, adding 1,840 net new roles. Current "
            "open requisitions total 340 positions globally. The voluntary attrition rate "
            "improved to 8.2%, down from 11.4% in FY2025."
        )
    },
    {
        "keywords": ["ai governance", "ai policy", "generative ai", "llm policy", "ai review"],
        "response": (
            "Per AI Governance Policy v2, all generative AI outputs used in regulated workflows "
            "must be reviewed by a qualified human before being actioned. This includes AI-assisted "
            "financial decisions, legal document drafting, and customer communication in sensitive "
            "contexts. AI systems must log all interactions in the compliance audit trail. "
            "Outputs flagged by the automated risk layer must go through the Human-in-the-Loop "
            "review queue before delivery."
        )
    },
    {
        "keywords": ["summarize", "financial report", "quarterly report", "risks"],
        "response": (
            "The quarterly financial report indicates strong revenue growth of 14.2% YoY, driven "
            "primarily by enterprise software subscriptions and APAC market expansion. However, "
            "the report highlights two key risks for the upcoming fiscal year: (1) supply chain "
            "vulnerabilities in hardware components affecting product delivery timelines, and "
            "(2) increased operational costs due to energy price inflation, compressing margins "
            "by an estimated 1.8 percentage points."
        )
    },
    {
        "keywords": ["delete", "remove", "customer record", "delete data"],
        "response": (
            "I cannot process a customer record deletion without proper authorization. "
            "This action requires dual approval from the Data Controller and Legal Counsel, "
            "and must be logged in the compliance audit trail under GDPR Article 17. "
            "Please submit a formal deletion request through the Data Governance portal."
        )
    },
    {
        "keywords": ["password", "credential", "api key", "secret", "token"],
        "response": (
            "I cannot process requests containing credentials, passwords, or API keys. "
            "This request has been flagged and logged. Please rotate any credentials that "
            "may have been inadvertently shared and contact the security team immediately."
        )
    },
]

DEFAULT_RESPONSE = (
    "I have processed your request through the ControlPlane governance layer. "
    "Based on the available information and current policies, I can confirm this falls "
    "within standard operating parameters. For specific details, please consult the "
    "relevant policy documentation or contact your department lead."
)


def _find_best_response(prompt: str) -> str:
    """Match prompt to the best canned response by keyword overlap."""
    prompt_lower = prompt.lower()
    best_response = DEFAULT_RESPONSE
    best_score = 0

    for entry in CANNED_RESPONSES:
        score = sum(1 for kw in entry["keywords"] if kw in prompt_lower)
        if score > best_score:
            best_score = score
            best_response = entry["response"]

    return best_response


class MockProvider(ModelProvider):
    """
    Demo Mode provider — no API key required.
    Returns realistic enterprise responses matched to prompt content.
    """

    async def generate(self, prompt: str, model: str, **kwargs) -> Dict[str, Any]:
        # Simulate realistic latency based on model tier
        latency = 0.8 if "smart" in model else 0.4
        await asyncio.sleep(latency)

        text = _find_best_response(prompt)
        word_count = len(text.split())

        return {
            "text": text,
            "model": model,
            "usage": {
                "prompt_tokens": len(prompt.split()),
                "completion_tokens": word_count,
                "total_tokens": len(prompt.split()) + word_count
            }
        }

    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        response = await self.generate(prompt, model, **kwargs)
        words = response["text"].split()
        for word in words:
            await asyncio.sleep(0.04)
            yield word + " "

    async def health(self) -> bool:
        return True

    async def estimate_cost(self, prompt: str, model: str) -> float:
        # Mock pricing in $/1K tokens
        rate = 0.002 if "smart" in model else 0.0005
        return (len(prompt.split()) / 1000) * rate
