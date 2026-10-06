.PHONY: install migrate run test
install:
	pip install -r requirements.txt
migrate:
	alembic upgrade head
run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000
test:
	pytest
