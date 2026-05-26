"""Behavior tree generation strategies and structural repair pass.

Four generation strategies:
  zero_shot              single LLM call without examples
  few_shot_generic       single LLM call with two SIL-unrelated example BTs
  proposed               three-call pipeline (decompose, elicit, synthesize)
  proposed_with_few_shot proposed pipeline with generic examples at synthesis

Structural repair (post-process) iteratively fixes BT.CPP load/tick failures
using only structural feedback from the validator. Coverage information is
never exposed to the LLM.
"""

from __future__ import annotations

from src.generators.llm_client import LLMClient
from src.prompts.templates import (
    FEW_SHOT_TEMPLATE,
    PROPOSED_DECOMPOSE_TEMPLATE,
    PROPOSED_ELICIT_TEMPLATE,
    PROPOSED_SYNTHESIZE_TEMPLATE,
    PROPOSED_SYNTHESIZE_WITH_EXAMPLES_TEMPLATE,
    STRUCTURAL_REPAIR_TEMPLATE,
    SYSTEM_PROMPT,
    ZERO_SHOT_TEMPLATE,
)

# Dimension count hint passed to the decompose step.
DIM_LO = 6
DIM_HI = 10

# Behaviors-per-dimension hint passed to the elicit step.
BEH_LO = 2
BEH_HI = 4

# Neutral system prompt for the proposed-pipeline intermediate calls
# (decompose, elicit). We do not want BT XML at these stages.
INTERMEDIATE_SYSTEM = (
    "You are an expert in simulation-based testing and behavior design for SIL "
    "environments. You are helping enumerate behaviors for an environment object "
    "in a simulation. Output plain text only - no XML, no code blocks."
)


class BTGenerator:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    # ---------------------------------------------------------------- zero-shot
    def zero_shot(self, object_name, object_description, domain, sut_description):
        prompt = ZERO_SHOT_TEMPLATE.format(
            object_name=object_name,
            object_description=object_description,
            domain=domain,
            sut_description=sut_description,
        )
        result = self.client.generate(SYSTEM_PROMPT, prompt)
        result["strategy"] = "zero_shot"
        result["call_count"] = 1
        return result

    # --------------------------------------------------------- few-shot generic
    def few_shot_generic(self, object_name, object_description, examples,
                         domain, sut_description):
        prompt = FEW_SHOT_TEMPLATE.format(
            object_name=object_name,
            object_description=object_description,
            examples=examples,
            domain=domain,
            sut_description=sut_description,
        )
        result = self.client.generate(SYSTEM_PROMPT, prompt)
        result["strategy"] = "few_shot_generic"
        result["call_count"] = 1
        return result

    # ----------------------------------------------------------------- proposed
    def proposed(self, object_name, object_description, domain, sut_description):
        return self._proposed_pipeline(
            object_name, object_description, domain, sut_description,
            examples=None, strategy_name="proposed",
        )

    # --------------------------------------------------- proposed + few-shot
    def proposed_with_few_shot(self, object_name, object_description, domain,
                               sut_description, examples):
        return self._proposed_pipeline(
            object_name, object_description, domain, sut_description,
            examples=examples, strategy_name="proposed_with_few_shot",
        )

    # ------------------------------------------- proposed pipeline (3 steps)
    def step_decompose(self, object_name, object_description, domain,
                       sut_description):
        prompt = PROPOSED_DECOMPOSE_TEMPLATE.format(
            object_name=object_name,
            object_description=object_description,
            domain=domain,
            sut_description=sut_description,
            n_lo=DIM_LO,
            n_hi=DIM_HI,
        )
        return self.client.generate(INTERMEDIATE_SYSTEM, prompt)

    def step_elicit(self, object_name, dimensions_text):
        prompt = PROPOSED_ELICIT_TEMPLATE.format(
            object_name=object_name,
            dimensions=dimensions_text,
            b_lo=BEH_LO,
            b_hi=BEH_HI,
        )
        return self.client.generate(INTERMEDIATE_SYSTEM, prompt)

    def step_synthesize(self, object_name, object_description, domain,
                        enumeration_text, examples=None):
        if examples:
            prompt = PROPOSED_SYNTHESIZE_WITH_EXAMPLES_TEMPLATE.format(
                object_name=object_name,
                object_description=object_description,
                domain=domain,
                enumeration=enumeration_text,
                examples=examples,
            )
        else:
            prompt = PROPOSED_SYNTHESIZE_TEMPLATE.format(
                object_name=object_name,
                object_description=object_description,
                domain=domain,
                enumeration=enumeration_text,
            )
        return self.client.generate(SYSTEM_PROMPT, prompt)

    def _proposed_pipeline(self, object_name, object_description, domain,
                           sut_description, examples, strategy_name):
        decompose = self.step_decompose(
            object_name, object_description, domain, sut_description,
        )
        elicit = self.step_elicit(object_name, decompose["content"])
        synth = self.step_synthesize(
            object_name, object_description, domain,
            elicit["content"], examples=examples,
        )
        return self._aggregate(
            steps=[("decompose", decompose), ("elicit", elicit), ("synthesize", synth)],
            strategy_name=strategy_name, synth_step=synth, examples=examples,
        )

    # ---------------------------------------------------------- bookkeeping
    def _aggregate(self, steps, strategy_name, synth_step, examples):
        total_prompt = sum(s[1]["usage"]["prompt_tokens"] for s in steps)
        total_completion = sum(s[1]["usage"]["completion_tokens"] for s in steps)
        total_elapsed = round(sum(s[1]["elapsed_seconds"] for s in steps), 2)

        pipeline_log = {}
        for name, step in steps:
            entry = {"usage": step["usage"]}
            if "content" in step and name != "synthesize":
                entry["content"] = step["content"]
            if name == "synthesize":
                entry["with_examples"] = examples is not None
            pipeline_log[name] = entry

        return {
            "content": synth_step["content"],
            "bt_xml": synth_step["bt_xml"],
            "usage": {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_prompt + total_completion,
            },
            "elapsed_seconds": total_elapsed,
            "model": synth_step["model"],
            "provider": synth_step.get("provider"),
            "seed": synth_step.get("seed"),
            "temperature": synth_step.get("temperature"),
            "strategy": strategy_name,
            "call_count": len(steps),
            "pipeline": pipeline_log,
        }

    # ------------------------------------------ repair (structural feedback)
    def structural_repair(self, bt_xml, validator_fn, max_iterations=3):
        """Iteratively repair structural errors in a BT.

        validator_fn(xml) should return None if the BT loads and ticks, or a
        string of error messages otherwise. Coverage is never passed back to
        the LLM; only structural feedback is used.
        """
        history = []
        current_xml = bt_xml
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_elapsed = 0.0
        repair_calls = 0

        for i in range(max_iterations):
            feedback = validator_fn(current_xml)
            if feedback is None:
                history.append({"iteration": i, "status": "ok"})
                break

            history.append({"iteration": i, "status": "repair_attempt",
                            "errors": feedback})
            repair_prompt = STRUCTURAL_REPAIR_TEMPLATE.format(
                feedback=feedback, previous_bt=current_xml,
            )
            repair = self.client.generate(SYSTEM_PROMPT, repair_prompt)
            repair_calls += 1
            total_prompt_tokens += repair["usage"]["prompt_tokens"]
            total_completion_tokens += repair["usage"]["completion_tokens"]
            total_elapsed += repair["elapsed_seconds"]

            if repair["bt_xml"]:
                current_xml = repair["bt_xml"]
            else:
                history.append({"iteration": i,
                                "status": "repair_failed_no_xml"})
                break
        else:
            feedback = validator_fn(current_xml)
            history.append({
                "iteration": max_iterations,
                "status": "ok" if feedback is None else "max_iterations_reached",
                "errors": feedback,
            })

        return {
            "bt_xml": current_xml,
            "repair_calls": repair_calls,
            "history": history,
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            },
            "elapsed_seconds": round(total_elapsed, 2),
        }
