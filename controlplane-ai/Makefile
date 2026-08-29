.PHONY: setup start-backend start-frontend test

setup:
	python -m venv venv
	.\venv\Scripts\activate && pip install -r backend/requirements.txt
	cd frontend && npm install

start-backend:
	.\venv\Scripts\activate && uvicorn backend.app.main:app --reload

start-frontend:
	cd frontend && npm run dev

test:
	.\venv\Scripts\activate && pytest backend/tests/
