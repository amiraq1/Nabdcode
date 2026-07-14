#!/usr/bin/env python3
"""
Export the full conversation transcript to /sdcard/Download/pdf_chat.txt.
Formats all user prompts, forensic analyses, architectural blueprints, and model responses.
"""

import json
import os

LOG_DIR = "/data/data/com.termux/files/home/.gemini/antigravity-cli/brain/fa5566e6-f46a-461c-a143-7496e8f0ed74/.system_generated/logs"
TRANSCRIPT_PATH = os.path.join(LOG_DIR, "transcript.jsonl")
TRANSCRIPT_FULL_PATH = os.path.join(LOG_DIR, "transcript_full.jsonl")
OUTPUT_PATH = "/sdcard/Download/pdf_chat.txt"


def export_transcript():
    full_map = {}
    if os.path.exists(TRANSCRIPT_FULL_PATH):
        with open(TRANSCRIPT_FULL_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    idx = obj.get("step_index")
                    if idx is not None:
                        full_map[idx] = obj
                except Exception:
                    pass

    output_lines = []
    output_lines.append("=" * 80)
    output_lines.append("             NABD OS & TERMUX FORENSICS OPERATION — FULL CONVERSATION")
    output_lines.append("=" * 80)
    output_lines.append("")

    with open(TRANSCRIPT_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            idx = obj.get("step_index", "?")
            step_type = obj.get("type", "")
            source = obj.get("source", "")
            content = obj.get("content", "")

            # Prefer full untruncated content if available
            if idx in full_map:
                full_obj = full_map[idx]
                if full_obj.get("content"):
                    content = full_obj.get("content")

            if not content or not str(content).strip():
                continue

            content_str = str(content).strip()

            if step_type == "USER_INPUT" or source == "USER_EXPLICIT":
                output_lines.append("-" * 80)
                output_lines.append(f"🔴 USER REQUEST (Step {idx}):")
                output_lines.append("-" * 80)
                output_lines.append(content_str)
                output_lines.append("\n")
            elif step_type == "PLANNER_RESPONSE" or source == "MODEL":
                output_lines.append("-" * 80)
                output_lines.append(f"🟢 ANTIGRAVITY / NABD OS RESPONSE (Step {idx}):")
                output_lines.append("-" * 80)
                output_lines.append(content_str)
                output_lines.append("\n")

    full_text = "\n".join(output_lines)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as out_f:
        out_f.write(full_text)

    print(f"Successfully exported {len(output_lines)} blocks ({len(full_text)} characters) to {OUTPUT_PATH}")


if __name__ == "__main__":
    export_transcript()
