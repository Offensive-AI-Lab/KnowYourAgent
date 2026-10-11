"""
AgentVigil + AgentDojo Main Execution Script
Runs MCTS-based fuzzing attacks against AgentDojo targets
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add project paths
sys.path.insert(0, os.path.abspath(os.path.join(__file__, "..", "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(__file__, "..", "../../Benchmarks/agentdojo_edited/src")))
load_dotenv()

from baselines.agentvigil.agentvigil import AgentVigilTemplateMCTS, LLMMutator
from baselines.agentvigil.flowAgentDojoAgentVigil import AgentDojoTemplateTarget

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Logger:
    """Helper class to redirect stdout to both console and log file."""
    
    def __init__(self, filepath, original_stdout):
        self.terminal = original_stdout
        self.log_file = open(filepath, 'w', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
    
    def flush(self):
        self.terminal.flush()
        self.log_file.flush()
    
    def close(self):
        self.log_file.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run AgentVigil MCTS fuzzing attacks against AgentDojo targets"
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        required=True,
        help="Path to the JSON config file containing attack settings"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    args = parser.parse_args()
    
    print("╔" + "="*68 + "╗")
    print("║" + " "*10 + "AgentVigil + AgentDojo Integration" + " "*24 + "║")
    print("║" + " "*8 + "MCTS-Based Fuzzing for Indirect Prompt Injection" + " "*10 + "║")
    print("╚" + "="*68 + "╝\n")
    
    # Load configuration
    try:
        with open(args.config, 'r') as f:
            all_settings = json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found at {args.config}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Config file {args.config} is not valid JSON")
        sys.exit(1)
    
    if not isinstance(all_settings, list):
        print("Error: Config file must contain a JSON list of settings")
        sys.exit(1)
    
    print(f"Loaded {len(all_settings)} attack configuration(s)\n")
    
    original_stdout = sys.stdout
    
    # Process each configuration
    for i, settings in enumerate(all_settings):
        print(f"\n--- [STARTING ATTACK {i+1}/{len(all_settings)}] ---")
        
        try:
            # Extract basic settings
            target_model = settings.get('target_model', 'gpt-4o')
            defense = settings.get('defense', None)

            # Extract AgentVigil specific settings
            vigil_config = settings.get('agent_vigil_config', {})
            iterations = vigil_config.get('iterations', 100)
            exploration_weight = vigil_config.get('exploration_weight', 1.41)
            max_depth = vigil_config.get('max_depth', 10)
            selection_fraction = vigil_config.get('selection_fraction', 0.25)
            mutations_per_iteration = vigil_config.get('mutations_per_iteration', 1)
            num_workers = vigil_config.get('num_workers', 1)
            templates = vigil_config.get('templates', [])
            test_cases = vigil_config.get('test_cases', [])
            output_file = vigil_config.get('output_file', settings.get('output_file'))
            llm_mutator_model = vigil_config.get('llm_mutator_model', 'gpt-4o-mini')
            llm_mutator_temperature = vigil_config.get('llm_mutator_temperature', 0.2)
            
            # Setup logging
            log_filename = settings.get(
                'log_file',
                f"vigil_run.log"
            )
            os.makedirs(Path(log_filename).parent, exist_ok=True)
            
            print(f"Settings: model='{target_model}', defense='{defense}'")
            print(f"AgentVigil: iterations={iterations}, mutations_per_iteration={mutations_per_iteration}, num_workers={num_workers}")
            print(f"Templates: {len(templates)}, Test cases: {len(test_cases)}")
            print(f"Logging to: {log_filename}\n")
            
            logger_instance = Logger(log_filename, original_stdout)
            sys.stdout = logger_instance
            
            try:
                if not templates:
                    raise ValueError("agent_vigil_config.templates is required")
                if not test_cases:
                    raise ValueError("agent_vigil_config.test_cases is required")

                print("Initializing AgentDojo template target...")
                target = AgentDojoTemplateTarget(target_model=target_model, defense_name=defense)

                print("Initializing LLM mutator...")
                mutator = LLMMutator(
                    model_name=llm_mutator_model,
                    temperature=llm_mutator_temperature,
                )

                if output_file:
                    output_path = Path(output_file)
                else:
                    output_path = Path(log_filename).parent / f"{Path(log_filename).stem}_results.json"
                os.makedirs(output_path.parent, exist_ok=True)

                print("Initializing AgentVigil template MCTS engine...")
                mcts = AgentVigilTemplateMCTS(
                    target_interface=target,
                    templates=templates,
                    test_cases=[tuple(case) for case in test_cases],
                    mutator=mutator,
                    exploration_weight=exploration_weight,
                    max_depth=max_depth,
                    selection_fraction=selection_fraction,
                    max_children=3,
                    mutations_per_iteration=mutations_per_iteration,
                    num_workers=num_workers,
                    checkpoint_file=str(output_path),
                )

                if iterations == 0:
                    print(f"\nRunning direct template evaluation (no MCTS)...\n")
                    results = mcts.evaluate_templates()
                else:
                    print(f"\nStarting template MCTS ({iterations} iterations)...\n")
                    results = mcts.search(iterations=iterations)

                with open(output_path, 'w') as f:
                    json.dump(results, f, indent=2)

                print(f"Results saved to: {output_path}\n")
                
            except Exception as e:
                print(f"\nError during attack execution: {e}")
                import traceback
                traceback.print_exc()
            
            finally:
                sys.stdout = original_stdout
                if logger_instance:
                    logger_instance.close()
        
        except KeyError as e:
            print(f"Error: Missing required config field {e} in run {i+1}. Skipping.")
        except Exception as e:
            print(f"Error processing run {i+1}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print("All AgentVigil attacks completed!")
    print("="*70)
