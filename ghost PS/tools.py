# imports
import json
from datetime import datetime, timedelta
import sqlite3 as sq
import sys
import urllib.request
import urllib.error
import time
from contextlib import closing

FILEPATH = "metrics.jsonl"

def find_first_error(filepath):
    """finds the first error in the cascading block of errors"""
    LATENCY_OFFSET = timedelta(milliseconds=12)  # hardcoded US-east-1 and US-east-2 latency diff
    error_logs = []
    buffer = 0.5  # length in duration for the sliding error checker
    FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
    min_count = 20  # min error count in the buffer to count it as a cascade of errors
    # didnt use error percentage or density because it be much slower for now

    with open(filepath, "r", encoding="utf-8") as file:
        for i, line in enumerate(file, 1):
            try:  # Catches partial or corrupted JSON writes in the log stream
                log = json.loads(line)
            except:
                continue
            if log.get("status") != 200:  # checking for errors this block will be different for different datasets
                try:  # in case the time is formatted wrong in the specific entry
                    current_time = datetime.strptime(log["ts"], FMT)
                except:
                    continue
                if log.get("zone") == "us-east-2":  # fixing the latency
                    current_time -= LATENCY_OFFSET
                log["ts"] = current_time
                error_logs.append(log)
                # Sliding window: drops older errors that fall outside the 0.5s threshold
                error_logs = [e for e in error_logs if (current_time - e["ts"]).total_seconds() <= buffer] 
                if len(error_logs) >= min_count:  # breaks if big block of erros is found
                    break
        if not error_logs:
            return None

        first_error = min(error_logs, key=lambda x: x["ts"])  # finds the first error in the block 
        first_error["ts"] = first_error["ts"].strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        return first_error

def get_configs(file_path="config.jsonl"):
    """parses through the config file somewhat redundant for now because config file only has one entry"""
    try:  # in case of wrong formatting or missing entries
        with open(file_path, "r") as f:
            config_data = json.load(f)
            return config_data["API_KEY"].strip()
    except Exception as e:
        print(f"Error loading config: {e}") 
        sys.exit(1)

def get_logs(db_path, limit_up=30, limit_down=20, target_ts=None, trace_id=None, service=None, status_code=None): 
    """function to fetch data filtered according  to specific condition from the sqlite database"""
    with closing(sq.connect(db_path)) as con:
        cursor = con.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:  # empty database
            print("Error: No tables found in database.")
            sys.exit(1)
            
        table_name = tables[0][0]

        if target_ts and not (trace_id or service or status_code):  # to find the data filtered by timestamp
            query = f""" 
                SELECT * FROM (
                    SELECT * FROM {table_name} WHERE ts < ? ORDER BY ts DESC LIMIT {limit_down}
                )
                UNION ALL
                SELECT * FROM (
                    SELECT * FROM {table_name} WHERE ts >= ? ORDER BY ts ASC LIMIT {limit_up}
                )
                ORDER BY ts ASC
            """ # query order
            cursor.execute(query, (target_ts, target_ts))

        else:
            conditions = []
            parameters = []
            
            if trace_id: 
                conditions.append("trace_id = ?")
                parameters.append(trace_id)
            if service:
                conditions.append("service = ?")
                parameters.append(service)
            if status_code:
                conditions.append("status = ?")
                parameters.append(status_code)
                
            if target_ts:
                conditions.append("ts <= ?")
                parameters.append(target_ts)
                
            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)
                
            total_limit = limit_up + limit_down
            query = f"SELECT * FROM {table_name} {where_clause} ORDER BY ts DESC LIMIT {total_limit}"  # query order
            
            cursor.execute(query, tuple(parameters))
            
        rows = cursor.fetchall()
        if not (target_ts and not (trace_id or service or status_code)):
            rows.reverse()
            
        columns = [desc[0] for desc in cursor.description]
    return columns, rows

def format_logs(col, logs):
    """formats the logs recieved to the ideal format"""
    formatted = []
    for i in logs:
        formatted.append(json.dumps(dict(zip(col, i))))
    return "\n".join(formatted)

def agent(api, url, prev_convo, prompt, max_retries=6):
    """sends the prompt to gemini and reciees its response"""
    new_message = {"role": "user", "parts": [{"text": prompt}]} # message format
    current_convo = prev_convo + [new_message]
    send = {"contents": current_convo}
    
    data = json.dumps(send).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    base_delay = 2
    
    for attempt in range(max_retries): 
        try: 
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                reply = result["candidates"][0]["content"]["parts"][0]["text"]
                return reply
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            
            # Checks for hard quota limit (do not retry)
            if "limit: 20" in error_body or "GenerateRequestsPerDay" in error_body:
                print(error_body)
                print("\n[FATAL] Daily quota exhausted.")
                sys.exit(1)
                
            # Check for throttle/busy errors (retry these)
            if e.code in [429, 503] or any(k in error_body for k in ["UNAVAILABLE", "RESOURCE_EXHAUSTED", "Overloaded"]):
                if attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt)
                    print(f"\n[!] API Busy/Throttled. Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(sleep_time)
                else:
                    print("\n[FATAL] Max retries reached.")
                    sys.exit(1)
            else:
                # If it's a 400 Bad Request or something else, crash so you can see the error
                raise Exception(f"HTTP Error {e.code}: {error_body}")
                
        except Exception as e:
            # Catch standard network connection drops
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt)
                print(f"\n[!] Network Error ({e}). Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(sleep_time)
            else:
                raise e
if __name__ == "__main__":
    pass