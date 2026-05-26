# PennerAI

**Washington Governance Intelligence** — Natural language access to audits, council actions, legislation, grants, and more.

A clean, trustworthy chat interface that lets anyone ask real questions about Washington state and local government and get accurate, cited answers.

Live demo: [https://wa-policy-graph-frontend.vercel.app](https://wa-policy-graph-frontend.vercel.app)

## What is PennerAI?

PennerAI turns messy, scattered public government data into something actually useful. 

It combines:
- Daily-updated Washington State Auditor reports
- City and county council minutes and actions
- Legislative data, budgets, grants, and more

…into one semantic database that you can talk to in plain English.

Ask questions like:
- “What audit findings does Tacoma have this year?”
- “Which cities increased police funding after high theft reports?”
- “Show me recent council actions on housing in Pierce County”

## Current Status

This is an early but functional version. The chat interface works and pulls from real data. We are actively improving the quality of answers, adding more data sources, and building personalized report features.

## License

This project is licensed under the **Business Source License 1.1** (BSL).  
You may use, modify, and test the code, but production/commercial use requires a commercial license until the Change Date.

**Change Date:** May 24, 2029  
**Change License:** Apache License 2.0

See the full [LICENSE](LICENSE) file for details.

## Tech Stack (High-Level)

- **Frontend**: Next.js (chat-first UI)
- **Backend**: FastAPI + PostgreSQL + pgvector
- **Data Pipeline**: Membrane-powered scrapers and extraction
- **Search**: Hybrid semantic + keyword search

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/thejoshuapenner/PennerAI-WPG.git
cd PennerAI-WPG

# 2. Start everything with Docker
docker-compose -f infra/docker-compose.yml up --build
```
