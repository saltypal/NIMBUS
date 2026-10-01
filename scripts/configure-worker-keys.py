"""Populate missing .env capability keys without printing secrets or replacing keys."""

import argparse
import secrets
from pathlib import Path


def configure(path):
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for capability in ("SPEECH", "HANDWRITING", "LLM"):
        name = f"NIMBUS_BRIDGE_{capability}_KEY"
        matches = [index for index, line in enumerate(lines) if line.startswith(name + "=")]
        if len(matches) > 1:
            raise ValueError(f"Remove duplicate {name} entries before configuring keys.")
        if matches and lines[matches[0]].split("=", 1)[1].strip():
            continue
        line = f"{name}={secrets.token_urlsafe(32)}"
        if matches:
            lines[matches[0]] = line
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"env_file": str(path.resolve()), "configured": ["speech", "handwriting", "llm"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    arguments = parser.parse_args()
    print(configure(arguments.env_file))
