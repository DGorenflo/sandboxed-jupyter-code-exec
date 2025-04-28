from fastapi import FastAPI, Form, HTTPException
import subprocess
from pydantic import BaseModel
import os
import queue
import asyncio
from jupyter_client import KernelManager
import nbformat
from nbformat.v4 import new_notebook
import time
from typing import Dict, Optional, List

# FastAPI instance
app = FastAPI()

# Base folders
BASE_FOLDER = "/mnt/data"
SESSIONS_FOLDER = "/mnt/jupyter_sessions"

class JupyterController:
    def __init__(self, folder_path):
        self.folder_path = folder_path
        self.notebook_path = None
        self.kernel_manager = None
        self.kernel_client = None
        self._kernel_ready = False

    async def _wait_for_kernel_ready(self, timeout=30):
        """Wait for kernel to be ready with proper timeout and checks"""
        start_time = time.time()
        while not self._kernel_ready:
            if time.time() - start_time > timeout:
                raise TimeoutError("Kernel failed to start within timeout period")

            try:
                if self.kernel_manager and self.kernel_manager.is_alive():
                    # Try a test execution to confirm readiness
                    self.kernel_client.execute("1+1")
                    # Clear out all messages from the test execution
                    while True:
                        try:
                            msg = self.kernel_client.get_iopub_msg(timeout=0.1)
                            if msg['header']['msg_type'] == 'status' and \
                               msg['content']['execution_state'] == 'idle':
                                break
                        except queue.Empty:
                            break

                    self._kernel_ready = True
                    break
            except Exception as e:
                # Log potential errors during kernel readiness check
                print(f"Kernel init check error: {str(e)}")
                pass # Allow loop to continue or timeout

            await asyncio.sleep(0.1)

    async def create_notebook(self, notebook_name):
        """Create notebook file and initialize kernel manager/client."""
        os.makedirs(self.folder_path, exist_ok=True)
        self.notebook_path = os.path.join(self.folder_path, f"{notebook_name}.ipynb")

        nb = new_notebook()
        with open(self.notebook_path, "w") as f:
            nbformat.write(nb, f)

        self.kernel_manager = KernelManager()
        self.kernel_manager.start_kernel()
        self.kernel_client = self.kernel_manager.client()
        self.kernel_client.start_channels()

        # Wait for kernel to be properly initialized
        await self._wait_for_kernel_ready()

        # Clear any remaining messages in the queue from startup
        self._clear_output_queue()

        return self.notebook_path

    def _clear_output_queue(self):
        """Clear any pending messages in the kernel's iopub queue."""
        while True:
            try:
                self.kernel_client.get_iopub_msg(timeout=0.1)
            except queue.Empty:
                break

    async def execute_code(self, code):
        """Execute code in the kernel, handling outputs and errors."""
        if not self._kernel_ready:
            # Try waiting again briefly in case of race condition before failing
            try:
                await self._wait_for_kernel_ready(timeout=5)
            except TimeoutError:
                 raise RuntimeError("Kernel not ready. Please wait for initialization or restart session.")
            if not self._kernel_ready:
                 raise RuntimeError("Kernel not ready after waiting. Please restart session.")


        if not self.kernel_manager.is_alive():
            self._kernel_ready = False
            raise RuntimeError("Kernel died. Please restart session.")

        # Clear any pending messages before execution
        self._clear_output_queue()

        msg_id = self.kernel_client.execute(code)
        outputs = []
        error_encountered = False

        while True:
            try:
                # Increased timeout for potentially longer operations
                msg = self.kernel_client.get_iopub_msg(timeout=20)
                msg_type = msg['header']['msg_type']
                content = msg['content']

                if msg_type == 'stream':
                    outputs.append(content['text'])
                elif msg_type == 'execute_result':
                    outputs.append(str(content['data'].get('text/plain', '')))
                elif msg_type == 'display_data':
                    # Handle different data types, omitting complex ones for brevity
                    if 'image/png' in content['data']:
                         outputs.append(f"[Image data: base64 PNG omitted]")
                    elif 'text/html' in content['data']:
                         outputs.append(f"[HTML data omitted]")
                    else:
                        text_data = content['data'].get('text/plain', '')
                        if text_data:
                            outputs.append(str(text_data))
                elif msg_type == 'error':
                    error_encountered = True
                    # Return error details in a structured way
                    error_detail = {
                        "error": "Execution error",
                        "ename": content.get('ename', 'UnknownError'),
                        "evalue": content.get('evalue', 'Unknown error value'),
                        "traceback": content.get('traceback', [])
                    }
                    # Raise HTTPException to be caught by FastAPI
                    raise HTTPException(
                        status_code=400, # Bad Request due to code error
                        detail=error_detail
                    )
                elif msg_type == 'status' and content['execution_state'] == 'idle':
                    # Check if this idle status corresponds to our execution request
                    if msg['parent_header']['msg_id'] == msg_id:
                        break # Exit loop once our execution is idle

            except queue.Empty:
                # Check if kernel is still alive before declaring timeout
                if not self.kernel_manager.is_alive():
                     self._kernel_ready = False
                     raise RuntimeError("Kernel died during execution. Please restart session.")
                else:
                    raise HTTPException(
                        status_code=408, # Request Timeout
                        detail="Code execution timed out waiting for response from kernel."
                    )
            except Exception as e:
                 # Catch unexpected errors during message handling
                 print(f"Error processing kernel message: {e}")
                 raise HTTPException(status_code=500, detail=f"Internal error processing kernel output: {str(e)}")


        return '\n'.join(outputs).strip() if outputs else ""

    async def reset_kernel(self):
        """Restart the kernel and wait for it to become ready."""
        if self.kernel_manager:
            print(f"Resetting kernel for session associated with: {self.folder_path}")
            self._kernel_ready = False
            try:
                self.kernel_manager.restart_kernel()
                await self._wait_for_kernel_ready()
                self._clear_output_queue()
                print(f"Kernel reset successful for: {self.folder_path}")
            except Exception as e:
                print(f"Error during kernel reset for {self.folder_path}: {e}")
                # Attempt cleanup if reset fails badly
                self.cleanup()
                raise RuntimeError(f"Failed to reset kernel: {e}")


    def cleanup(self):
        """Stop channels, shutdown kernel, and remove notebook file."""
        print(f"Cleaning up resources for session associated with: {self.folder_path}")
        if self.kernel_client:
            try:
                self.kernel_client.stop_channels()
            except Exception as e:
                print(f"Error stopping channels: {e}")
        if self.kernel_manager:
            try:
                if self.kernel_manager.is_alive():
                    self.kernel_manager.shutdown_kernel(now=True)
            except Exception as e:
                print(f"Error shutting down kernel: {e}")
        if self.notebook_path and os.path.exists(self.notebook_path):
            try:
                os.remove(self.notebook_path)
            except Exception as e:
                print(f"Error removing notebook file {self.notebook_path}: {e}")


# In-memory session tracking
class SessionInfo:
    """Holds information about an active user session."""
    def __init__(self, controller, created_at: float):
        self.controller = controller # The JupyterController instance for this session
        self.created_at = created_at # Timestamp when the session was created
        self.last_activity = created_at # Timestamp of the last interaction

# Dictionary to store active sessions, mapping conversation_id to SessionInfo
sessions: Dict[str, SessionInfo] = {}

# Pydantic model for the /run endpoint request body
class RunRequest(BaseModel):
    conversation_id: str
    code: str
    dependencies: Optional[List[str]] = [] # Optional list of pip package names

# Internal Helper Function
async def _create_session(conversation_id: str) -> SessionInfo:
    """Creates a new Jupyter session, kernel, notebook, and runs initial setup code."""
    if conversation_id in sessions:
        # Clean up existing session if it somehow exists before creation attempt
        print(f"Warning: Cleaning up existing session for {conversation_id} during creation request.")
        sessions[conversation_id].controller.cleanup()
        del sessions[conversation_id]

    session_folder = os.path.join(SESSIONS_FOLDER, conversation_id)
    controller = JupyterController(session_folder)

    try:
        print(f"Creating new session for: {conversation_id}")
        notebook_path = await controller.create_notebook(f"notebook_{conversation_id}")
        session_info = SessionInfo(controller, time.time())
        sessions[conversation_id] = session_info

        # Initialize common imports
        setup_code = """
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
# Set backend for matplotlib to Agg to avoid GUI issues in non-interactive env
import matplotlib
matplotlib.use('Agg')
print("Initial imports (pandas, numpy, matplotlib, os) loaded.")
        """
        # Execute setup code - handle potential errors during setup
        try:
            setup_output = await controller.execute_code(setup_code)
            print(f"Initial setup code executed for {conversation_id}. Output: {setup_output}")
        except Exception as setup_error:
             print(f"Error executing initial setup code for {conversation_id}: {setup_error}")
             # Clean up the session if setup fails
             controller.cleanup()
             del sessions[conversation_id]
             raise HTTPException(status_code=500, detail=f"Failed to initialize session environment: {setup_error}")


        print(f"Session created successfully for: {conversation_id}")
        return session_info
    except Exception as e:
        print(f"Error during session creation for {conversation_id}: {e}")
        controller.cleanup() # Ensure cleanup if creation fails at any point
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

# Internal Helper Function
async def _install_dependencies(session_info: SessionInfo, dependencies: List[str]):
    """Installs a list of dependencies using pip and attempts to import them in the kernel."""
    if not dependencies:
        return # Nothing to install

    controller = session_info.controller
    print(f"Installing dependencies for session {session_info.controller.folder_path}: {dependencies}")

    for package_name in dependencies:
        if not package_name: continue # Skip empty strings in the list

        try:
            print(f"Attempting to install {package_name}...")
            # Use python -m pip to ensure correct environment
            result = await asyncio.to_thread(
                subprocess.run,
                ["python", "-m", "pip", "install", package_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300  # 5 minute timeout per package
            )

            if result.returncode != 0:
                print(f"Failed pip install for {package_name}. Stderr: {result.stderr}")
                raise HTTPException(
                    status_code=400, # Bad request as dependency failed
                    detail=f"Failed to install dependency '{package_name}': {result.stderr or result.stdout}"
                )
            else:
                 print(f"Successfully installed {package_name}. Output: {result.stdout}")


            # If installation successful, try importing in the kernel
            # Basic import name extraction (handles simple cases like 'package-name', 'package==1.0')
            import_name = package_name.split('[')[0].split('==')[0].split('<')[0].split('>')[0].replace('-', '_')
            import_code = f"import {import_name}"
            print(f"Attempting to import {import_name} in kernel...")
            try:
                import_output = await controller.execute_code(import_code)
                print(f"Successfully imported {import_name}. Output: {import_output}")
            except HTTPException as import_error:
                 # If import fails after successful install, raise specific error
                 print(f"Failed to import {import_name} after installation: {import_error.detail}")
                 raise HTTPException(
                    status_code=400,
                    detail=f"Package '{package_name}' installed but failed to import in kernel: {import_error.detail}"
                 )

        except subprocess.TimeoutExpired:
            print(f"Timeout installing {package_name}")
            raise HTTPException(
                status_code=408, # Request Timeout
                detail=f"Package installation timed out for '{package_name}'"
            )
        except HTTPException:
             raise # Re-raise HTTPExceptions from install/import failures
        except Exception as e:
            print(f"Unexpected error installing {package_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Unexpected error installing dependency '{package_name}': {str(e)}")

# Helper function
async def get_session(conversation_id: str) -> SessionInfo:
    """Retrieves an existing session, updates activity time, and checks kernel readiness, attempting reset if needed."""
    if conversation_id not in sessions:
        raise HTTPException(status_code=404, detail=f"Session '{conversation_id}' not found. Please start a new session or check the ID.")

    session_info = sessions[conversation_id]
    session_info.last_activity = time.time() # Update activity time on access

    # Check kernel readiness more robustly
    if not session_info.controller.kernel_manager or not session_info.controller.kernel_manager.is_alive():
         session_info.controller._kernel_ready = False
         print(f"Kernel for session {conversation_id} found dead or uninitialized. Attempting reset...")
         try:
             # Try resetting if kernel is dead
             await session_info.controller.reset_kernel()
             # Re-run setup code after reset
             setup_code = """
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import matplotlib
matplotlib.use('Agg')
print("Re-running initial imports after kernel reset.")
             """
             await session_info.controller.execute_code(setup_code)
             print(f"Kernel for {conversation_id} reset successfully.")
         except Exception as reset_error:
             print(f"Failed to reset dead kernel for {conversation_id}: {reset_error}")
             # Cleanup the broken session if reset fails
             session_info.controller.cleanup()
             del sessions[conversation_id]
             raise HTTPException(status_code=500, detail=f"Kernel for session '{conversation_id}' died and could not be reset. Please start a new session.")

    elif not session_info.controller._kernel_ready:
        print(f"Kernel for session {conversation_id} not ready. Waiting...")
        try:
            await session_info.controller._wait_for_kernel_ready(timeout=15) # Wait for readiness
        except TimeoutError:
            print(f"Kernel for {conversation_id} timed out waiting for ready state. Attempting reset...")
            # If still not ready after waiting, try resetting
            try:
                await session_info.controller.reset_kernel()
                # Re-run setup code after reset
                setup_code = """
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import matplotlib
matplotlib.use('Agg')
print("Re-running initial imports after kernel reset.")
                """
                await session_info.controller.execute_code(setup_code)
                print(f"Kernel for {conversation_id} reset successfully after timeout.")
            except Exception as reset_error:
                 print(f"Failed to reset kernel for {conversation_id} after timeout: {reset_error}")
                 # Cleanup the broken session if reset fails
                 session_info.controller.cleanup()
                 del sessions[conversation_id]
                 raise HTTPException(status_code=500, detail=f"Kernel for session '{conversation_id}' failed to become ready and could not be reset. Please start a new session.")

    return session_info


# Background task for cleaning up inactive sessions
async def cleanup_inactive_sessions():
    """Periodically checks for and cleans up sessions inactive for more than an hour."""
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        current_time = time.time()
        to_remove = []
        # Copy keys first for safe iteration and removal
        session_ids = list(sessions.keys())

        for conversation_id in session_ids:
             # Check if session still exists (might have been removed by end_session)
             if conversation_id in sessions:
                session_info = sessions[conversation_id]
                # Check inactivity duration (1 hour)
                if current_time - session_info.last_activity > 3600:
                    print(f"Session {conversation_id} inactive for too long. Scheduling cleanup.")
                    to_remove.append(conversation_id)

        for conversation_id in to_remove:
            if conversation_id in sessions: # Double check before popping
                print(f"Executing cleanup for inactive session: {conversation_id}")
                session_info = sessions.pop(conversation_id)
                # Run cleanup in a separate task to avoid blocking the loop
                asyncio.create_task(asyncio.to_thread(session_info.controller.cleanup))
            else:
                 print(f"Session {conversation_id} already removed before scheduled cleanup.")


@app.on_event("startup")
async def startup_event():
    """Ensure sessions folder exists and start the background cleanup task."""
    os.makedirs(SESSIONS_FOLDER, exist_ok=True)
    asyncio.create_task(cleanup_inactive_sessions())

# Main endpoint for running code
@app.post("/run")
async def run_code_in_session(request: RunRequest):
    """
    Handles session creation/retrieval, dependency installation, and code execution.
    """
    conversation_id = request.conversation_id
    session_info: SessionInfo

    try:
        # Check if session exists, get it if it does
        if conversation_id in sessions:
            print(f"Getting existing session: {conversation_id}")
            session_info = await get_session(conversation_id) # Updates activity, checks kernel
        else:
            # Create new session if it doesn't exist
            print(f"No existing session found for {conversation_id}. Creating new one.")
            session_info = await _create_session(conversation_id)

        # Install dependencies if any are provided in the request
        if request.dependencies:
            await _install_dependencies(session_info, request.dependencies)

        # Execute the provided code in the session's kernel
        print(f"Executing code for session: {conversation_id}")
        output = await session_info.controller.execute_code(request.code)
        print(f"Code execution finished for {conversation_id}. Output length: {len(output)}")
        return {"output": output}

    except HTTPException as e:
         # Re-raise HTTPExceptions directly (e.g., from get_session, install, execute)
         print(f"HTTPException in /run for {conversation_id}: Status={e.status_code}, Detail={e.detail}")
         raise e
    except Exception as e:
        # Catch any other unexpected errors during the process
        print(f"Unexpected error in /run for {conversation_id}: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc() # Log full traceback for unexpected errors
        raise HTTPException(status_code=500, detail=f"An unexpected internal server error occurred: {str(e)}")


# Endpoint to reset a session's kernel
@app.post("/reset")
async def reset_session(conversation_id: str = Form(...)):
    """Resets the kernel for an existing session and re-runs initial setup code."""
    try:
        print(f"Received reset request for session: {conversation_id}")
        session_info = await get_session(conversation_id) # Get session, update activity, check kernel

        await session_info.controller.reset_kernel()

        # Reinitialize common imports after reset
        setup_code = """
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import matplotlib
matplotlib.use('Agg')
print("Re-running initial imports after manual reset.")
        """
        try:
            reset_output = await session_info.controller.execute_code(setup_code)
            print(f"Setup code executed after reset for {conversation_id}. Output: {reset_output}")
        except Exception as setup_error:
             print(f"Error executing setup code after reset for {conversation_id}: {setup_error}")
             # Session might be unstable, but don't kill it automatically here
             raise HTTPException(status_code=500, detail=f"Kernel reset, but failed to re-initialize environment: {setup_error}")


        return {"message": f"Kernel for session '{conversation_id}' reset successful"}
    except HTTPException as e:
         print(f"HTTPException in /reset for {conversation_id}: Status={e.status_code}, Detail={e.detail}")
         raise e
    except Exception as e:
        print(f"Unexpected error in /reset for {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset session '{conversation_id}': {str(e)}")

# Endpoint to end a session
@app.post("/end_session")
async def end_session(conversation_id: str = Form(...)):
    """Ends a specific session and schedules cleanup of its resources."""
    print(f"Received end session request for: {conversation_id}")
    if conversation_id not in sessions:
        # Return 404 Not Found if the session doesn't exist
        raise HTTPException(status_code=404, detail=f"Session '{conversation_id}' not found.")

    # Pop the session info first to prevent race conditions with cleanup task
    session_info = sessions.pop(conversation_id)
    print(f"Removed session {conversation_id} from active list.")

    # Perform cleanup asynchronously in the background using asyncio.to_thread
    try:
        asyncio.create_task(asyncio.to_thread(session_info.controller.cleanup))
        print(f"Cleanup task scheduled for session {conversation_id}")
        return {"message": f"Session '{conversation_id}' ended successfully and cleanup initiated."}
    except Exception as e:
         # This part might be hard to reach if cleanup runs in background
         print(f"Error initiating cleanup for {conversation_id}: {e}")
         # Even if cleanup initiation fails, the session is removed from the dict
         raise HTTPException(status_code=500, detail=f"Session removed, but error initiating cleanup: {str(e)}")