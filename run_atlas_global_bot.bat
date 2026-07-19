@echo off
cd C:\atlas-os
docker compose exec -T api python app/automation/run_scraper.py
docker compose exec -T api python -m app.automation.real_amazon_pipeline --max-videos 15
