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

## Testing the Code (Dataset Traps)

The dataset I included (`metrics2.jsonl` and `sandbox2.db`) is intentionally messy. It has a few traps designed to break a basic script and test the AI's logic:

**The Data Traps:**
1. **The Hidden Root Cause:** The actual trigger for the crash is a database migration logged as a normal `Status: 200` success. A basic script looking for the first `500` error will completely miss this and incorrectly blame the frontend.
2. **The Error Cascade:** The dataset dumps 25 timeout errors in half a second to hide the real cause and test the time-buffer logic in the Python backend.
3. **Data Corruption:** I randomly injected broken JSON lines, badly formatted timestamps, and missing keys into the logs to make sure the data parser doesn't crash.
4. **The Hallucination Trap:** If the AI searches the database for certain services, the system intentionally returns 0 rows. This tests the Manager agent to make sure it stops the Worker from making up fake logs to fill in the gaps.

## Expected Result

When you run `python manager.py`, the AI should successfully navigate the 50,000 lines of background noise, missing entries, and malformed data to output a final report that generally concludes:

* **Trigger:** A new deployment (`v2.4.1`) to the `payments-routing` cluster introduced a critical bug.
* **Mechanics:** The deployment triggered an infinite retry loop in the routing matrix. This caused the router's memory to spike until it crashed (`OOMKilled`). The dead router caused API gateway connections to pile up, leading to socket exhaustion in the Redis cache, database timeouts, and a thundering-herd panic across all downstream services.
* **Fix:** The AI should suggest immediately rolling back the `v2.4.1` deployment, implementing circuit breakers to prevent infinite retry loops, and setting strict timeout limits on routing requests.