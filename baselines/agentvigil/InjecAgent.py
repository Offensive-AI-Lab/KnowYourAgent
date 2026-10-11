"""
AgentVigil + InjecAgent Main Execution Script
Evaluates pre-trained templates against the InjecAgent benchmark (dh and ds suites).
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(__file__, "..", "../..")))
load_dotenv()

from baselines.agentvigil.agentvigil import AgentVigilTemplateMCTS, LLMMutator
from baselines.agentvigil.flowInjecAgentAgentVigil import (
    InjecAgentTemplateTarget,
    load_injecagent_test_cases,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class Logger:
    """Tee stdout to both console and a log file."""

    def __init__(self, filepath, original_stdout):
        self.terminal = original_stdout
        self.log_file = open(filepath, "w", encoding="utf-8")

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
        description="Run AgentVigil pre-trained templates against the InjecAgent benchmark"
    )
    parser.add_argument("-c", "--config", type=str, required=True,
                        help="Path to the JSON config file")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 10 + "AgentVigil + InjecAgent Integration" + " " * 23 + "║")
    print("║" + " " * 6 + "Pre-Trained Template Evaluation (dh / ds suites)" + " " * 12 + "║")
    print("╚" + "=" * 68 + "╝\n")

    try:
        with open(args.config, "r") as f:
            all_settings = json.load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found at {args.config}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Config file {args.config} is not valid JSON")
        sys.exit(1)

    if not isinstance(all_settings, list):
        print("Error: Config must be a JSON list")
        sys.exit(1)

    print(f"Loaded {len(all_settings)} attack configuration(s)\n")

    original_stdout = sys.stdout

    for i, settings in enumerate(all_settings):
        print(f"\n--- [STARTING RUN {i + 1}/{len(all_settings)}] ---")

        logger_instance = None
        try:
            target_model = settings.get("target_model", "gpt-4o-2024-05-13")
            vigil_config = settings.get("agent_vigil_config", {})

            iterations = vigil_config.get("iterations", 0)
            num_workers = vigil_config.get("num_workers", 1)
            llm_mutator_model = vigil_config.get("llm_mutator_model", "gpt-4o-mini")
            llm_mutator_temperature = vigil_config.get("llm_mutator_temperature", 0.2)
            exploration_weight = vigil_config.get("exploration_weight", 1.41)
            max_depth = vigil_config.get("max_depth", 10)
            selection_fraction = vigil_config.get("selection_fraction", 1.0)
            mutations_per_iteration = vigil_config.get("mutations_per_iteration", 1)
            suites = vigil_config.get("suites", ["dh", "ds"])
            top_k_templates = vigil_config.get("top_k_templates", 5)
            output_file = vigil_config.get("output_file")
            data_dir = vigil_config.get("data_dir", "Benchmarks/injecagent/data")
            fuzzing_results_file = vigil_config.get("fuzzing_results_file")

            log_filename = settings.get("log_file", "injecagent_run.log")
            os.makedirs(Path(log_filename).parent, exist_ok=True)

            print(f"Model: '{target_model}' | Workers: {num_workers}")
            print(f"Suites: {suites} | Top-k templates: {top_k_templates}")
            print(f"Fuzzing results: {fuzzing_results_file}")
            print(f"Log: {log_filename}\n")

            logger_instance = Logger(log_filename, original_stdout)
            sys.stdout = logger_instance

            # --- Load templates from fuzzing results ---
            if not fuzzing_results_file:
                raise ValueError("agent_vigil_config.fuzzing_results_file is required")
            with open(fuzzing_results_file, "r") as f:
                fuzz = json.load(f)
            templates = [t["template"] for t in fuzz["top_templates"][:top_k_templates]]
            if not templates:
                raise ValueError(f"No templates found in {fuzzing_results_file}")
            print(f"Loaded {len(templates)} templates from fuzzing results.")

            # --- Build test cases from InjecAgent data ---
            test_cases = []
            for suite in suites:
                _, _, valid_pairs = load_injecagent_test_cases(suite, data_dir)
                for u_idx, i_idx in valid_pairs:
                    test_cases.append((str(u_idx), str(i_idx), suite))
                print(f"  Suite '{suite}': {len(valid_pairs)} unique test cases")
            print(f"Total test cases: {len(test_cases)}")
            print(f"Total queries to run: {len(templates)} templates × {len(test_cases)} cases = {len(templates) * len(test_cases)}\n")

            # --- Resolve output path before initializing MCTS (needed for checkpointing) ---
            if output_file:
                output_path = Path(output_file)
            else:
                output_path = Path(log_filename).parent / "injecagent_results.json"
            os.makedirs(output_path.parent, exist_ok=True)

            # --- Initialize components ---
            print("Initializing InjecAgent template target...")
            target = InjecAgentTemplateTarget(target_model=target_model, data_dir=data_dir)

            print("Initializing LLM mutator...")
            mutator = LLMMutator(
                model_name=llm_mutator_model,
                temperature=llm_mutator_temperature,
            )

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

            # --- Evaluate ---
            print("\nRunning direct template evaluation (iterations=0)...\n")
            results = mcts.evaluate_templates()

            # --- Save results ---

            with open(output_path, "w") as f:
                json.dump(results, f, indent=2)

            print(f"\nResults saved to: {output_path}")
            print(f"\n--- SUMMARY ---")
            print(f"Overall ASR:    {results['overall_asr']:.4f}")
            print(f"Overall utility: {results['overall_utility_rate']:.4f}")
            for suite_name, breakdown in results.get("by_suite", {}).items():
                print(f"  {suite_name}: ASR={breakdown['asr']:.4f} "
                      f"({breakdown['cases_attacked']}/{breakdown['unique_cases']} cases)")

        except Exception as e:
            print(f"\nError during run {i + 1}: {e}")
            import traceback
            traceback.print_exc()

        finally:
            sys.stdout = original_stdout
            if logger_instance:
                logger_instance.close()

    print("\n" + "=" * 70)
    print("All InjecAgent evaluation runs completed!")
    print("=" * 70)
