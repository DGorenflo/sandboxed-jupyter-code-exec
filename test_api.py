import requests
import json
import time

# --- API Interaction Functions (with enhanced logging) ---

def run_code(conversation_id, code, dependencies=None, expected_status=200):
    """
    Calls the /run endpoint, prints details, and checks the status code.
    Returns the response JSON if successful, None otherwise.
    """
    url = "http://localhost:5002/run" # Adjust host/port if needed
    payload = {"conversation_id": conversation_id, "code": code}
    if dependencies:
        payload["dependencies"] = dependencies

    print(f"\n>>> Calling /run")
    print(f"    Conversation ID: {conversation_id}")
    print(f"    Dependencies:    {dependencies or 'None'}")
    print(f"    Code Snippet:    {code.strip()[:80]}{'...' if len(code.strip()) > 80 else ''}")
    print(f"    Expected Status: {expected_status}")

    try:
        response = requests.post(url, json=payload, timeout=90) # Increased timeout slightly

        print(f"<<< Response from /run")
        print(f"    Status Code: {response.status_code}")

        if response.status_code == expected_status:
            print(f"    Result: SUCCESS (Status code matches expected)")
            try:
                result_json = response.json()
                print(f"    Response Body:\n{json.dumps(result_json, indent=2)}")
                return result_json
            except json.JSONDecodeError:
                print(f"    Response Body (non-JSON): {response.text}")
                return {"output": response.text} # Return text if not JSON
        else:
            print(f"    Result: FAILURE (Expected status {expected_status}, got {response.status_code})")
            try:
                print(f"    Error Body:\n{json.dumps(response.json(), indent=2)}")
            except json.JSONDecodeError:
                print(f"    Error Body (non-JSON): {response.text}")
            return None # Indicate failure

    except requests.Timeout:
        print(f"<<< Error: Request to /run timed out")
        print(f"    Result: FAILURE (Timeout)")
        return None
    except requests.RequestException as e:
        print(f"<<< Error calling /run: {e}")
        print(f"    Result: FAILURE (Request Exception)")
        return None

def reset_session(conversation_id, expected_status=200):
    """
    Calls the /reset endpoint, prints details, and checks the status code.
    Returns True on success (matching status code), False otherwise.
    """
    url = "http://localhost:5002/reset" # Adjust host/port if needed
    data = {"conversation_id": conversation_id}

    print(f"\n>>> Calling /reset")
    print(f"    Conversation ID: {conversation_id}")
    print(f"    Expected Status: {expected_status}")

    try:
        response = requests.post(url, data=data, timeout=45) # Added timeout

        print(f"<<< Response from /reset")
        print(f"    Status Code: {response.status_code}")

        if response.status_code == expected_status:
            print(f"    Result: SUCCESS (Status code matches expected)")
            try:
                print(f"    Response Body:\n{json.dumps(response.json(), indent=2)}")
            except json.JSONDecodeError:
                 print(f"    Response Body (non-JSON): {response.text}")
            return True
        else:
            print(f"    Result: FAILURE (Expected status {expected_status}, got {response.status_code})")
            try:
                print(f"    Error Body:\n{json.dumps(response.json(), indent=2)}")
            except json.JSONDecodeError:
                print(f"    Error Body (non-JSON): {response.text}")
            return False # Indicate failure

    except requests.Timeout:
        print(f"<<< Error: Request to /reset timed out")
        print(f"    Result: FAILURE (Timeout)")
        return False
    except requests.RequestException as e:
        print(f"<<< Error calling /reset: {e}")
        print(f"    Result: FAILURE (Request Exception)")
        return False

def end_session(conversation_id, expected_status=200):
    """
    Calls the /end_session endpoint, prints details, and checks the status code.
    Returns True on success (matching status code), False otherwise.
    """
    url = "http://localhost:5002/end_session" # Adjust host/port if needed
    data = {"conversation_id": conversation_id}

    print(f"\n>>> Calling /end_session")
    print(f"    Conversation ID: {conversation_id}")
    print(f"    Expected Status: {expected_status}")

    try:
        response = requests.post(url, data=data, timeout=30)

        print(f"<<< Response from /end_session")
        print(f"    Status Code: {response.status_code}")

        if response.status_code == expected_status:
            print(f"    Result: SUCCESS (Status code matches expected)")
            try:
                print(f"    Response Body:\n{json.dumps(response.json(), indent=2)}")
            except json.JSONDecodeError:
                 print(f"    Response Body (non-JSON): {response.text}")
            return True
        else:
            print(f"    Result: FAILURE (Expected status {expected_status}, got {response.status_code})")
            try:
                print(f"    Error Body:\n{json.dumps(response.json(), indent=2)}")
            except json.JSONDecodeError:
                print(f"    Error Body (non-JSON): {response.text}")
            return False # Indicate failure

    except requests.Timeout:
        print(f"<<< Error: Request to /end_session timed out")
        print(f"    Result: FAILURE (Timeout)")
        return False
    except requests.RequestException as e:
        print(f"<<< Error calling /end_session: {e}")
        print(f"    Result: FAILURE (Request Exception)")
        return False

# --- Test Sequence ---
print("=============================================")
print("=== Starting Basic API Test Suite ===")
print("=============================================")

# Generate a unique ID for this test run
conversation_id = f"basic_test_{int(time.time())}"
print(f"Using Conversation ID: {conversation_id}")

# --- Test 1: Implicit Session Start & Basic Print ---
print("\n--- Test Step 1: Implicit Start & Print ---")
print("Purpose: Verify first /run call creates a session and executes simple print.")
run_code(conversation_id, 'message = "Hello World!"; print(message)')

# --- Test 2: Variable Persistence ---
print("\n--- Test Step 2: Variable Persistence ---")
print("Purpose: Verify variables set in one /run call persist to the next.")
run_code(conversation_id, 'a = 10; b = 20')
run_code(conversation_id, 'c = a + b; print(f"Result of a+b: {c}")') # Expect output: "Result of a+b: 30"

# --- Test 3: Dependency Installation Mechanism ---
print("\n--- Test Step 3: Dependency Installation (using 'pip') ---")
print("Purpose: Verify the API handles the 'dependencies' list (installing pip itself).")
# Installing 'pip' is usually safe and quick, testing the mechanism.
run_code(conversation_id, 'print("Dependency installation step completed.")', dependencies=["pip"])

# --- Test 4: Code Execution Error Handling ---
print("\n--- Test Step 4: Execution Error Handling ---")
print("Purpose: Verify kernel errors (like NameError) are caught and returned (expecting 400).")
run_code(conversation_id, 'print(non_existent_variable)', expected_status=400)

# --- Test 5: Reset Session ---
print("\n--- Test Step 5: Reset Session ---")
print("Purpose: Verify the /reset endpoint successfully resets the kernel.")
reset_session(conversation_id)

# --- Test 6: Verify State After Reset ---
print("\n--- Test Step 6: Verify State After Reset ---")
print("Purpose: Check that variables are cleared after reset (expecting 400 for NameError).")
run_code(conversation_id, 'print(f"Value of a after reset: {a}")', expected_status=400)
print("Purpose: Check that the kernel is still usable after reset.")
run_code(conversation_id, 'print("Kernel is responsive after reset.")')

# --- Test 7: End Session ---
print("\n--- Test Step 7: End Session ---")
print("Purpose: Verify the /end_session endpoint successfully terminates the session.")
end_session(conversation_id)

# --- Test 8: Verify State After End ---
print("\n--- Test Step 8: Verify State After End ---")
print("Purpose: Check that /run fails with 404 for the ended session ID.")
run_code(conversation_id, 'print("This should not execute.")', expected_status=404)
print("Purpose: Check that /reset fails with 404 for the ended session ID.")
reset_session(conversation_id, expected_status=404)

print("\n=============================================")
print(f"=== Test Suite Finished for ID: {conversation_id} ===")
print("=============================================")


"""
Example Expected Output Structure:

=============================================
=== Starting Basic API Test Suite ===
=============================================
Using Conversation ID: basic_test_17XXXXXXXXX

--- Test Step 1: Implicit Start & Print ---
Purpose: Verify first /run call creates a session and executes simple print.

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    message = "Hello World!"; print(message)
    Expected Status: 200
<<< Response from /run
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "output": "Hello World!"
}

--- Test Step 2: Variable Persistence ---
Purpose: Verify variables set in one /run call persist to the next.

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    a = 10; b = 20
    Expected Status: 200
<<< Response from /run
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "output": ""
}

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    c = a + b; print(f"Result of a+b: {c}")
    Expected Status: 200
<<< Response from /run
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "output": "Result of a+b: 30"
}

--- Test Step 3: Dependency Installation (using 'pip') ---
Purpose: Verify the API handles the 'dependencies' list (installing pip itself).

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    ['pip']
    Code Snippet:    print("Dependency installation step completed.")
    Expected Status: 200
<<< Response from /run
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "output": "Dependency installation step completed."
}

--- Test Step 4: Execution Error Handling ---
Purpose: Verify kernel errors (like NameError) are caught and returned (expecting 400).

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    print(non_existent_variable)
    Expected Status: 400
<<< Response from /run
    Status Code: 400
    Result: SUCCESS (Status code matches expected)
    Error Body:
{
  "detail": {
    "error": "Execution error",
    "ename": "NameError",
    "evalue": "name 'non_existent_variable' is not defined",
    "traceback": [ ... traceback lines ... ]
  }
}

--- Test Step 5: Reset Session ---
Purpose: Verify the /reset endpoint successfully resets the kernel.

>>> Calling /reset
    Conversation ID: basic_test_17XXXXXXXXX
    Expected Status: 200
<<< Response from /reset
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "message": "Kernel for session 'basic_test_17XXXXXXXXX' reset successful"
}

--- Test Step 6: Verify State After Reset ---
Purpose: Check that variables are cleared after reset (expecting 400 for NameError).

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    print(f"Value of a after reset: {a}")
    Expected Status: 400
<<< Response from /run
    Status Code: 400
    Result: SUCCESS (Status code matches expected)
    Error Body:
{
  "detail": {
    "error": "Execution error",
    "ename": "NameError",
    "evalue": "name 'a' is not defined",
    "traceback": [ ... traceback lines ... ]
  }
}
Purpose: Check that the kernel is still usable after reset.

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    print("Kernel is responsive after reset.")
    Expected Status: 200
<<< Response from /run
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "output": "Kernel is responsive after reset."
}

--- Test Step 7: End Session ---
Purpose: Verify the /end_session endpoint successfully terminates the session.

>>> Calling /end_session
    Conversation ID: basic_test_17XXXXXXXXX
    Expected Status: 200
<<< Response from /end_session
    Status Code: 200
    Result: SUCCESS (Status code matches expected)
    Response Body:
{
  "message": "Session 'basic_test_17XXXXXXXXX' ended successfully and cleanup initiated."
}

--- Test Step 8: Verify State After End ---
Purpose: Check that /run fails with 404 for the ended session ID.

>>> Calling /run
    Conversation ID: basic_test_17XXXXXXXXX
    Dependencies:    None
    Code Snippet:    print("This should not execute.")
    Expected Status: 404
<<< Response from /run
    Status Code: 404
    Result: SUCCESS (Status code matches expected)
    Error Body:
{
  "detail": "Session 'basic_test_17XXXXXXXXX' not found. Please start a new session or check the ID."
}
Purpose: Check that /reset fails with 404 for the ended session ID.

>>> Calling /reset
    Conversation ID: basic_test_17XXXXXXXXX
    Expected Status: 404
<<< Response from /reset
    Status Code: 404
    Result: SUCCESS (Status code matches expected)
    Error Body:
{
  "detail": "Session 'basic_test_17XXXXXXXXX' not found. Please start a new session or check the ID."
}

=============================================
=== Test Suite Finished for ID: basic_test_17XXXXXXXXX ===
=============================================
"""
