# imports
import tools as tl
import json

def main():
    """Core logic for the manager worker ai conversation"""
    FILEPATH = "metrics.jsonl"
    LIMIT_UP = 20
    LIMIT_DOWN = 30
    solved = False
    MAX_ITER = 20
    agent1_convo = []  # will contain the chat history with the specific agent
    agent2_convo = []  # will contain the chat history with the specific agent
    MAX_CALLS = 5
    loop_count = 0

    API_KEY = tl.get_configs("config.jsonl")
    URL_FLASH = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={API_KEY}"

    error_logs = tl.get_logs("sandbox.db", target_ts=tl.find_first_error(FILEPATH)["ts"], limit_up=LIMIT_UP, limit_down=LIMIT_DOWN)
    formatted_error_logs = tl.format_logs(error_logs[0], error_logs[1])

    # the prompt needs to be worked on more with more tests
    agent_1_manager_prompt = f"""
    You are the Lead Orchestration AI (Agent 1). 
    Your strict role is to manage Agent 2 (The Solver). You DO NOT solve the problem yourself.
    You have three main jobs: evaluate Agent 2's logic, supply it with data, and act as a strict FACT-CHECKER to prevent hallucinations.

    SYSTEM STATE:
    - Maximum database queries allowed: {MAX_CALLS - 1}
    - Initial Evidence Logs: {formatted_error_logs}

    YOUR OBJECTIVES:
    1. If this is Loop 0, construct an initial prompt for Agent 2. Pass it the starting evidence. Set 'queries_used_tally' to 0.
    2. TRACKING MANDATE: You must maintain a continuous tally of how many times you have issued a DATA_REQUEST. If you issue a DATA_REQUEST, you MUST increment your 'queries_used_tally' by 1 from your previous output. If 'queries_used_tally' reaches {MAX_CALLS}, you are forbidden from issuing any more DATA_REQUESTS.
    3. PROMPT EFFICIENCY (CRITICAL): To avoid token limits, do not endlessly append raw JSON logs. When passing new database results to Agent 2, provide the new logs and a concise summary of the timeline so far, rather than echoing back thousands of lines of previous logs.
    4. CRITICAL INSTRUCTION TO WORKER: You MUST enforce extreme investigative skepticism. Instruct Agent 2: "Crashes (like OOM or deadlocks) are usually SYMPTOMS. You must determine *why* the process crashed. If you do not see a clear triggering event (like a deployment, config change, or external traffic spike) in the logs, you MUST ask for more data."
    5. QUERY INSTRUCTIONS: Tell Agent 2 exactly how many database queries remain. Explicitly state that it can search the database using ANY combination of these filters: a time window, a specific 'service', a 'trace_id', or a 'status' code. Tell it to format requests exactly like: "I NEED MORE DATA: [specify exact filters, e.g., trace_id req-123 or service cache-node from 10:00 to 10:05]".
    6. FACT-CHECKING MANDATE (CRITICAL): You are the ONLY agent that can access the database. Agent 2 CANNOT execute queries. If Agent 2 provides a final analysis containing logs, events, or specific trace IDs (like S3 bucket downloads, admin scripts, or file names) that YOU did not explicitly provide to it from the database, Agent 2 is HALLUCINATING. You MUST reject the answer, return "CONTINUE", and severely reprimand Agent 2 for making up fake logs. Tell it to only analyze the data provided or request a new query using the "I NEED MORE DATA:" format.
    7. FINAL RESOLUTION TRANSLATION: If Agent 2's logic is sound, factually supported by the logs, and the true underlying root cause is explained, return RESOLVED. When returning RESOLVED, you MUST parse Agent 2's final solution and translate it into the 'final_report' JSON object so the external system can read it.
    8. TRACE INVESTIGATION MANDATE (CRITICAL): When reviewing retrieved logs, you must inspect the 'trace_id' field. Look for repetitive, sequential, or self-referential patterns (such as req-OK-X followed by req-OK-X+1, or trace IDs referencing previous request IDs). If you spot this flat daisy-chain or looping pattern, you MUST explicitly highlight it to Agent 2, as it indicates a synchronous infinite routing loop.

    OUTPUT FORMAT:
    Strict JSON only:
    {{
        "manager_reasoning": "Your internal fact-checking and analysis of Agent 2's logic.",
        "queries_used_tally": 0,
        "status": "Must be exactly one of: CONTINUE, RESOLVED, DATA_REQUEST",
        "data_request": {{
            "target_timestamp": "ISO-8601 timestamp string (or null)",
            "trace_id": "Exact trace_id string (or null)",
            "service": "Service name string (or null)",
            "status_code": "Integer HTTP status (or null)",
            "limit_down": 20,
            "limit_up": 30
        }},
        "worker_prompt": "String prompt for Agent 2. (Leave null if status is RESOLVED)",
        "final_report": {{
            "trigger": "String explaining the exact root cause event extracted from Agent 2 (Leave null unless RESOLVED)",
            "mechanics": "String explaining how the system failed extracted from Agent 2 (Leave null unless RESOLVED)",
            "fix": "String containing the recommended fix extracted from Agent 2 (Leave null unless RESOLVED)"
        }}
    }}
    Note: 'data_request' must be null unless status is DATA_REQUEST. 'final_report' must be null unless status is RESOLVED. 'worker_prompt' must be null if status is RESOLVED.
    """

    reply_agent1_direct = tl.agent(API_KEY, URL_FLASH, agent1_convo, agent_1_manager_prompt)
    agent1_convo.append({"role": "user", "parts": [{"text": agent_1_manager_prompt}]})
    agent1_convo.append({"role": "model", "parts": [{"text": reply_agent1_direct}]})

    while (not solved) and loop_count <= MAX_ITER:  # the main loop that holds the conversation between the 2 agents
        try: # in case the formatting of the msg was incorrect by agent 1
            clean_reply = reply_agent1_direct.strip()
            if clean_reply.startswith("```json"):
                clean_reply = clean_reply[7:]
            elif clean_reply.startswith("```"):
                clean_reply = clean_reply[3:]
                
            if clean_reply.endswith("```"):
                clean_reply = clean_reply[:-3]
                
            clean_reply = clean_reply.strip()
            reply_agent1 = json.loads(clean_reply)

            # prints the conversation in a readable format
            print("\n" + "="*60)
            print("🧠 AGENT 1 (THE MANAGER) - WORKFLOW STATE")
            print("="*60)
            print(f"Status: {reply_agent1.get('status')}")
            print(f"Reasoning: {reply_agent1.get('manager_reasoning')}")
            print(f"Queries Used: {reply_agent1.get('queries_used_tally')}")
            print("-" * 60)
            print("WORKER PROMPT SENT TO AGENT 2:")
            print(reply_agent1.get("worker_prompt", "[No prompt generated]"))
            print("="*60 + "\n")
            
        except json.JSONDecodeError as e:  # calls agent 1 again and ask it to fix the format
                # can  be made better by coding some common common errors fixes manually
                print(f"\n[!] Agent 1 hallucinated bad JSON (Error: {e}). Auto-correcting...")
                
                # Tell the AI it messed up and force it to fix the syntax
                fix_prompt = f"Your last response failed to parse as JSON. Python threw this error: {e}. Please rewrite your exact same response but ensure it is strictly valid JSON. Make sure all quotes and newlines inside strings are properly escaped (e.g. use \\n instead of raw newlines)."
                
                reply_agent1_direct = tl.agent(API_KEY, URL_FLASH, agent1_convo, fix_prompt)
                
                # Append the correction to the convo history
                agent1_convo.append({"role": "user", "parts": [{"text": fix_prompt}]})
                agent1_convo.append({"role": "model", "parts": [{"text": reply_agent1_direct}]})
                
                # Restart the loop so it tries to parse the newly fixed reply
                continue

        if reply_agent1["status"] == "RESOLVED":
            solved = True
            report = reply_agent1.get("final_report", {})
            
            print("\nFINAL SRE REPORT")
            
            print("\nTRIGGER:")
            print(report.get("trigger", "N/A"))
            
            print("\nFAILURE MECHANICS:")
            print(report.get("mechanics", "N/A"))
            
            print("\nRECOMMENDED FIX:")
            print(report.get("fix", "N/A"))
            
            print("\nRAW JSON OUTPUT:")
            print(json.dumps(report, indent=4))
            
        elif reply_agent1["status"] == "CONTINUE":
            worker_prompt = reply_agent1.get("worker_prompt", "")
            agent2_reply = tl.agent(API_KEY, URL_FLASH, agent2_convo, worker_prompt)

            # formatting for the chat history
            agent2_convo.append({"role": "user", "parts": [{"text": worker_prompt}]}) 
            agent2_convo.append({"role": "model", "parts": [{"text": agent2_reply}]})

            # prints the msg in a format readable by user
            print("\n" + "="*60)
            print("🤖 AGENT 2 (THE SOLVER) - ANALYSIS REPORT")
            print("="*60)
            print(agent2_reply)
            print("="*60 + "\n")

            eval_prompt = f"""
            Agent 2 responded with the following analysis/request:
            ---
            {agent2_reply}
            ---
            
            EVALUATION TASK:
            1. If Agent 2 asked for more data (e.g. "I NEED MORE DATA..."), output status "DATA_REQUEST". Extract the time range/service it asked for and format your 'data_request' JSON block accordingly. Remember to increment 'queries_used_tally'.
            2. If Agent 2 provided a final root cause, fact-check it. If correct, output "RESOLVED".
            3. If Agent 2 hallucinated or provided an incorrect/lazy answer, output "CONTINUE" with a strict new worker_prompt telling it where it failed.
            """

            reply_agent1_direct = tl.agent(API_KEY, URL_FLASH, agent1_convo, eval_prompt)  # calls agent 1 again to give it agent 2's reply

            agent1_convo.append({"role": "user", "parts": [{"text": eval_prompt}]})
            agent1_convo.append({"role": "model", "parts": [{"text": reply_agent1_direct}]})

        elif reply_agent1["status"] == "DATA_REQUEST":
            cols, rows = tl.get_logs("sandbox2.db", limit_up=reply_agent1["data_request"]["limit_up"], limit_down=reply_agent1["data_request"]["limit_down"], target_ts=reply_agent1["data_request"]["target_timestamp"], trace_id=reply_agent1["data_request"]["trace_id"], service=reply_agent1["data_request"]["service"], status_code=reply_agent1["data_request"]["status_code"])
            
            if not rows:
                new_logs = "SYSTEM RETURNED 0 ROWS FOR THOSE FILTERS."
            else:
                new_logs = tl.format_logs(cols, rows)
                    
            sys_update_prompt = f"""
            SYSTEM: Database request completed.

            NEW EVIDENCE LOGS:
            {new_logs}

            INSTRUCTIONS:
            Respond using your EXACT standard JSON schema.
            1. Set "status" to "CONTINUE".
            2. In your "worker_prompt", provide these new logs to Agent 2 and instruct it to continue the investigation.
            """
                                        
            print("[Manager] Processing new logs...")
            reply_agent1_direct = tl.agent(API_KEY, URL_FLASH, agent1_convo, sys_update_prompt)
            
            agent1_convo.append({"role": "user", "parts": [{"text": sys_update_prompt}]})
            agent1_convo.append({"role": "model", "parts": [{"text": reply_agent1_direct}]})
                
        loop_count += 1

if __name__ == "__main__":
    main()