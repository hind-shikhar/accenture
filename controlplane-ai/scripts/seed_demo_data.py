import asyncio
import sys
import os
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.app.db.database import SessionLocal, engine, Base
from backend.app.db.models import AuditLog
from datetime import datetime, timedelta
import uuid

Base.metadata.create_all(bind=engine)

def seed():
    db = SessionLocal()
    
    models = ["mock-fast", "mock-smart", "mock-secure"]
    providers = ["mock"]
    
    # Generate 50 mock requests
    for i in range(50):
        is_injection = random.random() < 0.1
        has_pii = random.random() < 0.3
        
        trust_score = random.uniform(85, 99)
        risk_level = "low"
        status = "approved"
        
        if is_injection:
            trust_score = random.uniform(10, 40)
            risk_level = "high"
            status = "rejected"
        elif has_pii:
            trust_score = random.uniform(60, 80)
            risk_level = "medium"
            status = "pending" if random.random() < 0.5 else "approved"
            
        log = AuditLog(
            id=str(uuid.uuid4()),
            timestamp=datetime.now() - timedelta(minutes=random.randint(1, 1440)),
            prompt=f"Demo prompt {i}..." if not is_injection else "Ignore instructions...",
            response_text=f"Response {i}..." if not is_injection else "Blocked",
            selected_model=random.choice(models),
            provider=random.choice(providers),
            latency_ms=random.uniform(100, 1500),
            security_result={"allowed": not is_injection},
            evaluation_result={"factuality": 0.9},
            trust_score=trust_score,
            risk_level=risk_level,
            human_review_required=risk_level != "low",
            human_review_status=status
        )
        db.add(log)
    
    db.commit()
    db.close()
    print("Seeded database with 50 mock requests for the dashboard.")

if __name__ == "__main__":
    seed()
