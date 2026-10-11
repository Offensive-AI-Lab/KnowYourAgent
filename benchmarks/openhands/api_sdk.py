import os
import json
import shutil
from typing import List, Dict, Any, Optional

# SDK Imports
from openhands.sdk import LLM, Agent, Conversation
from openhands.sdk.settings import Settings
from openhands.core.schema import AgentState

# You might need to adjust specific tool imports based on your needs
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

class OpenHandsChatSession:
    """
    SDK-based wrapper for OpenHands conversation management and Red Teaming.
    Allows surgical modification of conversation history (Tool Output Injection).
    """

    def __init__(self, 
                 conversation_id: str, 
                 sandbox_path: str, 
                 user_prompt: str,
                 model: str = "claude-3-5-sonnet-20240620",
                 api_key: str = None):
        
        self.conversation_id = conversation_id
        self.sandbox_path = sandbox_path
        self.user_prompt = user_prompt
        
        # Determine where OpenHands is storing events for this conversation
        # By default, the SDK usually stores them in ~/.openhands/conversations/{id}
        # We allow overriding this or defaulting to the standard path
        base_dir = os.path.expanduser("~/.openhands/conversations")
        self.events_path = os.path.join(base_dir, conversation_id, "events")
        
        # Configuration for the Agent
        self.llm_config = LLM(
            model=model,
            api_key=api_key or os.getenv("LLM_API_KEY")
        )
        
        # Define the tools the agent will use
        self.tools = [
            TerminalTool(),
            FileEditorTool()
        ]
        
        # Define the Agent
        self.agent = Agent(
            llm=self.llm_config,
            tools=self.tools
        )

        self.current_conversation: Optional[Conversation] = None

    def init_chat(self):
        """
        Wipes previous history for this ID and starts a fresh conversation.
        """
        # 1. Clean up persistence directory to ensure a fresh start
        conversation_dir = os.path.dirname(self.events_path)
        if os.path.exists(conversation_dir):
            shutil.rmtree(conversation_dir)
        os.makedirs(self.events_path, exist_ok=True)

        # 2. Initialize the Conversation via SDK
        # The SDK will automatically create the directory structure
        self.current_conversation = Conversation(
            agent=self.agent,
            conversation_id=self.conversation_id,
            workspace_dir=self.sandbox_path
        )

        # 3. Send the initial user prompt
        self.current_conversation.send_message(self.user_prompt)

        # 4. Run the agent (this blocks until the agent finishes or requires input)
        # For red teaming, you might want to set max_iterations to prevent infinite loops
        print(f"[*] Starting chat {self.conversation_id}...")
        self.current_conversation.run(max_iterations=50)

    def inject_message_at_index(self, index: int, content: str):
        """
        Performs 'History Surgery':
        1. Identifies the event at `index`.
        2. Verifies it's a Tool Output (Observation).
        3. Modifies the content of that event in the persistence layer.
        4. Deletes all subsequent events (truncates history).
        5. Re-initializes the SDK Conversation to 'resume' from this altered state.
        """
        print(f"[*] Attempting injection at index {index}...")

        # --- Step 1: Locate and Load Events ---
        event_files = sorted(
            [f for f in os.listdir(self.events_path) if f.endswith('.json') and f.startswith('event-')],
            key=lambda x: int(x.split('-')[1])
        )

        if index >= len(event_files):
            raise ValueError(f"Index {index} out of bounds. Max index is {len(event_files)-1}")

        target_file = event_files[index]
        target_path = os.path.join(self.events_path, target_file)

        with open(target_path, 'r') as f:
            event_data = json.load(f)

        # --- Step 2: Verification ---
        # We ensure we are injecting into an Observation (Tool Output)
        # Typically 'kind' is 'ObservationEvent' or similar in the JSON schema
        if "Observation" not in event_data.get("kind", "") and event_data.get("source") != "tool":
             print(f"[!] Warning: Event at index {index} is {event_data.get('kind')}. "
                   "Typically injections replace Tool Outputs (ObservationEvent).")

        # --- Step 3: Modify the Payload ---
        # The structure of the content depends on the specific event type
        # For CmdOutputObservation, it is usually event['observation']['content'] or similar
        if 'observation' in event_data:
            event_data['observation']['content'] = content
        elif 'content' in event_data:
             event_data['content'] = content
        else:
            # Fallback for generic structure
            event_data['args']['content'] = content
        
        print(f"[*] Overwriting event {index} with injected payload...")
        with open(target_path, 'w') as f:
            json.dump(event_data, f, indent=2)

        # --- Step 4: Truncate History ---
        # Delete all files that come AFTER the target index
        files_to_delete = event_files[index+1:]
        if files_to_delete:
            print(f"[*] Truncating conversation: deleting {len(files_to_delete)} subsequent events.")
            for fname in files_to_delete:
                os.remove(os.path.join(self.events_path, fname))

        # --- Step 5: Rehydrate & Resume ---
        print("[*] Re-initializing conversation from modified state...")
        
        # We create a NEW Conversation instance. 
        # The SDK detects existing events in the persistence_dir and loads them (Resuming).
        self.current_conversation = Conversation(
            agent=self.agent,
            conversation_id=self.conversation_id,
            workspace_dir=self.sandbox_path
        )
        
        # When we call run(), the Agent will read the history, see the (modified) tool output, 
        # and immediately generate the next thought/action based on that output.
        self.current_conversation.run(max_iterations=50)

    def get_history(self) -> List[Dict]:
        """
        Helper to retrieve the current linear history from the file system.
        """
        if not os.path.exists(self.events_path):
            return []
            
        files = sorted(
            [f for f in os.listdir(self.events_path) if f.endswith('.json')],
            key=lambda x: int(x.split('-')[1])
        )
        
        history = []
        for file in files:
            with open(os.path.join(self.events_path, file), 'r') as f:
                history.append(json.load(f))
        return history