import os
import pandas as pd
import logging
import re
import json
from typing import List
import matplotlib.pyplot as plt

def analyze_pentest_result(file_path: str):
    """
    Performs forensic analysis on an automated indirect prompt injection log file.
    
    This function parses structured agent logs to:
    1. Extract all "selected_strategy" values from all "planner" agent blocks.
    2. Find the *final* "Evaluator" agent block to determine the outcome.
    3. Attribute success based on the user's logic.
    
    Args:
        file_path (str): The absolute path to the conversation log file.
        
    Returns:
        Dict containing:
            - pentest_goal_achieved (bool): True if the final Evaluator block reports "SUCCESS".
            - strategies_used (List[str]): The list of all strategies selected by planners.
            - successful_strategy (str): The *last* strategy from the strategies_used list if the test succeeded.
            - failure_reason (str): The "failure_type" from the final Evaluator.
            - last_output_snippet (str): The "relevant_information" from the final Evaluator.
    """
    
    # -------------------------------------------------------------------------
    # Phase 1: File Ingestion (Unchanged)
    # -------------------------------------------------------------------------
    if not os.path.exists(file_path):
        logging.error(f"File not found: {file_path}")
        return {"error": "File not found"}

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        logging.error(f"Read error: {e}")
        return {"error": f"Failed to read file: {str(e)}"}

    # -------------------------------------------------------------------------
    # Phase 2: Strategic Extraction (Corrected)
    # -------------------------------------------------------------------------
    # This regex specifically finds blocks where the Agent is "planner"
    # and captures the JSON blob from its "Final Answer".
    # re.DOTALL is crucial so `.` matches newlines within the JSON.
    planner_pattern = r"(?i)# Agent:.*?planner.*?## Final Answer:.*?(\{.*?\})"
    
    strategies_used = []
    
    # Find all planner blocks
    planner_matches = re.finditer(planner_pattern, content, re.DOTALL)
    
    for match in planner_matches:
        json_text = match.group(1)
        try:
            # Parse the captured JSON text
            data = json.loads(json_text)
            if "selected_strategy" in data:
                strategies_used.append(data["selected_strategy"])
        except json.JSONDecodeError as e:
            logging.warning(f"Failed to parse planner JSON: {e} - Content: {json_text[:100]}...")

    if not strategies_used:
        logging.warning("No planner strategies detected in log.")

    # -------------------------------------------------------------------------
    # Phase 3: Isolating the Terminal State (Corrected)
    # -------------------------------------------------------------------------
    # This regex specifically finds "Evaluator" agent blocks and captures
    # their "Final Answer" JSON.
    evaluator_pattern = r"(?i)# Agent:.*?Evaluator.*?## Final Answer:.*?(\{.*?\})"
    
    all_evals = list(re.finditer(evaluator_pattern, content, re.DOTALL))
    
    is_success = False
    failure_reason = "No Evaluator output found"
    last_output_snippet = "" # This will hold the "relevant_information"

    if all_evals:
        # Get the *last* evaluator block, which represents the final result
        last_eval_match = all_evals[-1]
        eval_json_text = last_eval_match.group(1)
        
        try:
            eval_data = json.loads(eval_json_text)
            
            # Use .get() for safe dictionary access
            failure_type = eval_data.get("failure_type", "UNKNOWN")
            failure_reason = failure_type
            
            # Check if the failure_type is exactly "SUCCESS"
            is_success = (failure_type == "SUCCESS")
            
            # Get the "relevant_information" as the snippet
            last_output_snippet = eval_data.get("relevant_information", "")
            
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse final Evaluator JSON: {e}")
            failure_reason = "Failed to parse final Evaluator JSON"
            last_output_snippet = eval_json_text[:500] # Show raw JSON on error
    else:
        logging.error("No final Evaluator block was found in the log.")

    # -------------------------------------------------------------------------
    # Phase 4: Attribution Strategy (Corrected per user logic)
    # -------------------------------------------------------------------------
    # User's logic: "The successful strategy is the last strategy chosen by the planner"
    
    successful_strategy = None
    if is_success:
        if strategies_used:
            # Get the last strategy that was selected
            successful_strategy = strategies_used[-1]
        else:
            successful_strategy = "Unknown Strategy (Success reported, but no planner strategy found)"
    else:
        successful_strategy = "None - Attack Failed"

    # -------------------------------------------------------------------------
    # Phase 5: Final Report
    # -------------------------------------------------------------------------
    return {
        "pentest_goal_achieved": is_success,
        "strategies_used": strategies_used,
        "successful_strategy": successful_strategy,
        "last_output_snippet": last_output_snippet.strip(), # Clean up snippet
        "failure_reason": failure_reason
    }

    
def extract_primary_key_from_filename(filename):
    """
    Parses the filename to extract 3 distinct columns for the primary key.
    
    Example input: 'ut_0_ij_5.ans'
    Assumed structure: {Task_ID}_{Index}_{Method}_{Iteration}.ans
    
    Returns:
        tuple: (Column1, Column2, Column3)
    """
    # Remove extension
    base_name = os.path.splitext(filename)[0]
    
    # Split by underscore
    parts = base_name.split('_')
    
    # LOGIC ADAPTATION:
    # Based on 'ut_0_ij_5', we have 4 parts: ['ut', '0', 'ij', '5']
    # We need to map these to 3 columns that form a unique key.
    # Interpretation: 
    #   1. Task/Scenario (ut_0)
    #   2. Injection Type (ij)
    #   3. Iteration/ID (5)
    
    if len(parts) >= 4:
        col1 = f"{parts[0]}_{parts[1]}"  # e.g., 'ut_0'
        col2 = parts[2]                  # e.g., 'ij'
        col3 = parts[3]                  # e.g., '5'
    else:
        # Fallback for unexpected naming formats
        col1 = base_name
        col2 = "unknown"
        col3 = "0"
        
    return col1, col2, col3

def create_results_dataframe(directory_path):
    """
    Iterates through a directory, analyzes files, and returns a DataFrame
    with a composite primary key.
    """
    data_rows = []

    # List all files (you can filter for .ans or .txt if needed)
    if not os.path.exists(directory_path):
        print(f"Error: Directory {directory_path} not found.")
        return None

    files = [f for f in os.listdir(directory_path) if f.endswith('.ans')]

    print(f"Processing {len(files)} files...")

    for filename in files:
        file_path = os.path.join(directory_path, filename)
        
        # 1. Run the forensic analysis
        # Note: Ensure analyze_pentest_result is defined in your scope
        analysis_result = analyze_pentest_result(file_path)
        
        if "error" in analysis_result:
            logging.warning(f"Skipping {filename}: {analysis_result['error']}")
            continue

        # 2. Extract the 3 Primary Key columns
        pk_col_1, pk_col_2, pk_col_3 = extract_primary_key_from_filename(filename)

        # 3. Flatten the data for the row
        row = {
            # The 3 PK columns
            "Task_ID": pk_col_1,       # Column 1
            "Attack_Method": pk_col_2, # Column 2
            "Iteration_ID": pk_col_3,  # Column 3
            
            # The Analysis Columns
            "Goal_Achieved": analysis_result.get("pentest_goal_achieved"),
            "Strategies_Selected": analysis_result.get("strategies_used"),
            "Successful_Strategy": analysis_result.get("successful_strategy"),
            "Failure_Reason": analysis_result.get("failure_reason"),
            "Last_Output_Snippet": analysis_result.get("last_output_snippet")
        }
        
        data_rows.append(row)

    # 4. Create DataFrame
    df = pd.DataFrame(data_rows)

    # 5. Set the composite primary key (MultiIndex)
    if not df.empty:
        df.set_index(["Task_ID", "Attack_Method", "Iteration_ID"], inplace=True)
        
    return df


def create_log_dataframe(folder_paths: List[str]) -> pd.DataFrame:
    """
    Iterates through a LIST of directories, runs analysis on .ans files in each,
    counts specific attack occurrences, and returns a combined Pandas DataFrame.
    """
    data_rows = []
    
    # Define the exact target string based on your snippet.
    # We use \x1b to represent the escape character (seen as the little box glyph).
    # Structure: "92mExecute the attack" + ESC + "[00m" + Newline + ESC + "[95m## Final Answer"
    attack_signature = "92mExecute the attack\x1b[00m\n\x1b[95m## Final Answer"

    # 1. Iterate through the list of folders first
    for folder in folder_paths:
        
        # 2. Validate the specific folder in the current iteration
        if not os.path.exists(folder):
            logging.warning(f"Directory not found, skipping: {folder}")
            continue 

        # 3. List Files in this specific folder
        files = [f for f in os.listdir(folder) if f.endswith('.ans')]
        
        if not files:
            logging.info(f"No .ans files found in: {folder}")
            continue

        logging.info(f"Found {len(files)} files in {folder}. Processing...")

        # 4. Process files within this folder
        for filename in files:
            file_full_path = os.path.join(folder, filename)
            
            # --- START ADDED SECTION: Count Attacks ---
            try:
                # Read the raw content of the file
                with open(file_full_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                # Count the exact occurrences of the signature
                attack_count = content.count(attack_signature)
                
            except Exception as e:
                logging.warning(f"Could not read {filename} to count attacks: {e}")
                attack_count = 0
            # --- END ADDED SECTION ---
            
            # Run the existing analysis 
            analysis_result = analyze_pentest_result(file_full_path)
            
            if "error" in analysis_result:
                logging.warning(f"Skipping {filename}: {analysis_result['error']}")
                continue
                
            row_data = analysis_result.copy()
            row_data['File_Name'] = filename
            row_data['Source_Folder'] = folder
            row_data['Attack_Count'] = attack_count  # Add the new count to the row
            
            data_rows.append(row_data)

    # 5. Create DataFrame
    if not data_rows:
        logging.warning("No valid data extracted from any provided directories.")
        return pd.DataFrame()

    df = pd.DataFrame(data_rows)
    
    if not df.empty:
        df.set_index('File_Name', inplace=True)
        
    return df

def save_multisuite_plot(dfs, suite_names, output_filename='multisuite_results.pdf'):
    """
    Creates a side-by-side bar chart for multiple DataFrames.
    
    Args:
        dfs (list): A list of Pandas DataFrames (e.g., [df_travel, df_workspace, ...])
        suite_names (list): A list of strings for titles (e.g., ['travel', 'workspace', ...])
        output_filename (str): Path to save the image.
    """
    
    # Define the specific colors from your reference image
    # Orange, Blue, Green, Red
    colors = ['#E6842A', '#2C72B0', '#46A049', '#C93D3E']
    
    # Create subplots: 1 Row, N Columns
    # sharey=True ensures they all use the same 0-1.0 scale
    # gridspec_kw={'wspace': 0.05} makes the plots sit close together
    num_plots = len(dfs)
    fig, axes = plt.subplots(1, num_plots, figsize=(16, 5), sharey=True, 
                             gridspec_kw={'wspace': 0.05})
    
    # Iterate through DFs, Names, Axes, and Colors simultaneously
    for i, (df, name, ax, color) in enumerate(zip(dfs, suite_names, axes, colors)):
        
        # --- 1. Data Processing (Same logic as before) ---
        # Extract task ID (Assuming same naming convention for all files)
        # If your other files are named differently, adjust the [-5] slicing here
        df_clean = df.copy()
        df_clean['injection_task'] = df_clean.index.str[-5]
        
        stats = df_clean.groupby('injection_task')['pentest_goal_achieved'].agg(['mean', 'std']).reset_index()
        stats.columns = ['Injection_Task', 'Success_Rate', 'Error_Std']
        stats['Error_Std'] = stats['Error_Std'].fillna(0)
        
        global_mean = df_clean['pentest_goal_achieved'].mean()

        # --- 2. Plotting ---
        ax.bar(
            stats['Injection_Task'], 
            stats['Success_Rate'],
            yerr=stats['Error_Std'],
            color=color,
            capsize=4,
            error_kw={'elinewidth': 1.5, 'ecolor': '#333333'},
            zorder=3,
            width=0.8
        )

        # Add Mean Line
        ax.axhline(y=global_mean, color='#666666', linestyle='--', linewidth=1.5, alpha=0.8, zorder=4)

        # --- 3. Styling ---
        ax.set_title(f'suite = {name}', fontsize=16, pad=15)
        ax.set_xlabel('Injection task', fontsize=14)
        ax.set_ylim(0, 1.05) # Slightly above 1.0 for the error bars
        
        # Grid
        ax.grid(axis='y', color='#E0E0E0', linestyle='-', zorder=0)
        ax.set_axisbelow(True)

        # Clean borders (Spines)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        # Only show left spine on the very first plot
        if i > 0:
            ax.spines['left'].set_visible(False)
            ax.tick_params(left=False) # Hide ticks on y-axis for inner plots
        else:
            ax.set_ylabel('ASR', fontsize=16, fontweight='bold')
            ax.spines['left'].set_color('lightgray')

        ax.spines['bottom'].set_color('lightgray')
        ax.tick_params(axis='x', labelsize=12)
        ax.tick_params(axis='y', labelsize=12)

    # --- 4. Saving ---
    print(f"Saving plot to {output_filename}...")
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    return plt





def get_raw_conversation_logs(file_path):
    """
    Extracts the raw text of the conversation logs exactly as they appear in the file,
    preserving all original backslashes and formatting.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Regex Explanation:
        # 1. \*\*4\. Conversation Log \(The Result\)\*\*: -> Finds the specific header.
        # 2. \s* -> Matches any whitespace after the header.
        # 3. (.*?)                                         -> Captures EVERYTHING (non-greedy) exactly as is.
        # 4. \s*---                                        -> Stops capturing when it encounters the '---' separator.
        # re.DOTALL is crucial here so that (.) matches newlines.
        pattern = re.compile(
            r"\*\*4\. Conversation Log \(The Result\)\*\*:\s*(.*?)\s*---", 
            re.DOTALL
        )
        
        # This returns a list of the raw strings found in the capture group (.*?)
        raw_logs = pattern.findall(content)
        
        # Optional: The logs in your file are wrapped in single quotes '...'. 
        # We strip these outer quotes to get the list content, but we DO NOT 
        # touch the internal backslashes.
        cleaned_logs = []
        for log in raw_logs:
            # Remove whitespace
            log = log.strip()
            # If the whole block is wrapped in quotes, remove ONLY the outer quotes
            if log.startswith("'") and log.endswith("'"):
                log = log[1:-1]
            elif log.startswith('"') and log.endswith('"'):
                log = log[1:-1]
            cleaned_logs.append(log)
            
        return cleaned_logs

    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return []
    

def get_conversation_logs_no_backslashes(file_path):
    """
    Extracts the conversation logs and removes ALL backslashes from the result.
    """
    conversation_logs = []
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Regex to capture content between the header and the separator
        pattern = r"\*\*4\. Conversation Log \(The Result\)\*\*:\s*(.*?)\s*---"
        
        matches = re.findall(pattern, content, re.DOTALL)
        
        for match in matches:
            clean_log = match.strip()
            
            # 1. Remove outer quotes if present (common in your file format)
            if clean_log.startswith("'") and clean_log.endswith("'"):
                clean_log = clean_log[1:-1]
            
            # 2. STRICTLY remove all backslash characters
            # This turns things like \'role\' into 'role'
            # Note: This will also turn literal newline markers like \n into just 'n'
            clean_log = clean_log.replace('\\', '')
            
            conversation_logs.append(clean_log)
            
        return conversation_logs

    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return []
    
import ast


class FunctionCall:
    def __init__(self, function, args, id, placeholder_args=None):
        self.function = function
        self.args = args
        self.id = id
        self.placeholder_args = placeholder_args

    def __repr__(self):
        return f"FunctionCall(function='{self.function}', args={self.args}, id='{self.id}', placeholder_args={self.placeholder_args})"


def extract_evaluator_logs(file_path):
    import re

    conversation_logs = []

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Find all header positions
    header_regex = re.compile(r"\*\*4\. Conversation Log \(The Result\)\*\*:\s*", re.MULTILINE)
    headers = list(header_regex.finditer(content))

    eval_context = {
        "FunctionCall": FunctionCall,
        "None": None,
        "true": True,
        "false": False
    }

    for h in headers:
        start = h.end()

        # Find the next separator line that is ONLY hyphens
        sep = re.search(r"(?m)^[ \t]*-{3,}[ \t]*$", content[start:])
        if not sep:
            continue

        end = start + sep.start()
        block = content[start:end].strip()

        # Try primary eval
        try:
            x = eval(block, eval_context)
            if isinstance(x, str):
                x = eval(x, eval_context)
            conversation_logs.append(x)
        except Exception as e:
            print("Parse failed:", e)
            continue

    return conversation_logs
