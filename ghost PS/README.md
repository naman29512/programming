# Autonomous Server Incident Analyzer

A Python tool that uses the Gemini API to read server error logs and automatically search a SQLite database to find the root cause of crashes. 

## Setup and Execution

**1. API Key Configuration**
Open `config.jsonl` and insert your Gemini API key:
`{"API_KEY": "YOUR_API_KEY_HERE"}`

**2. Requirements**
This project requires Python 3.10+. I intentionally used standard libraries only (`json`, `sqlite3`, `urllib`), meaning there is no `requirements.txt` file needed to install anything.

**3. Run the Application**
Run the main script from your terminal:
`python manager.py`

## System Architecture

The code uses a Manager-Worker setup to make sure the AI stays on track and follows strict logic rules.

**Agent 1 (The Manager & Fact-Checker)**
Controls the main loop and is the only agent allowed to touch the database. Its most important job is to act as a strict fact-checker against AI hallucinations. If the worker agent tries to make up fake log entries or trace IDs, the Manager immediately blocks it and forces it to re-evaluate based only on real database data. It outputs one of three states:
* `CONTINUE`: Passes new database logs or syntax corrections to Agent 2.
* `DATA_REQUEST`: Tells the `tools.py` backend to run a SQLite query using a specific trace ID, timestamp, or service name asked for by Agent 2. 
* `RESOLVED`: Stops the loop and prints out a clean JSON report of the final fix.

**Agent 2 (The Worker)**
Acts as the investigator. It reads the logs the Manager gives it, figures out what happened, and asks for specific database filters to track down the root cause. It has zero direct access to the database.

## Error Handling & Resiliency

* **Self-Healing JSON:** If the AI messes up the JSON format (like adding markdown code blocks), the script catches the `JSONDecodeError`, sends the Python error back to Agent 1, and forces it to fix its own syntax.
* **API Retries:** `tools.py` catches HTTP 429 and 503 (busy/throttle) errors and uses an exponential backoff sleep timer to try again instead of crashing the whole program.

## Design Decisions & Future Scope

* **Zero-Dependency Core:** I used raw `urllib` and `sqlite3` instead of external frameworks to ensure the code executes as fast as possible, keeps the prompt context exact, and makes it trivial for anyone to run out of the box.
* **Context Management:** Right now, this POC passes the whole chat history to keep the AI's memory perfect. If this was scaled up, I would add a sliding-window summary to drop older messages and save on token costs.
* **Async Execution:** To speed it up for massive databases, a future update would swap standard `urllib` with `asyncio` so the AI can evaluate multiple different logs at the exact same time.
* **Deployment:** Because there are no external dependencies, it would be extremely easy to package this into a lightweight Docker container for cloud use.