#!/usr/bin/env python3
"""Run the official Cosmos CLI while resolving its pinned checkpoint locally."""

from __future__ import annotations

import os
from pathlib import Path


COSMOS_REPOSITORY = "nvidia/Cosmos3-Edge"


def main() -> None:
    checkpoint = Path(os.environ["OVERSEAARK_COSMOS_LOCAL_CHECKPOINT"]).resolve()
    if not checkpoint.is_dir():
        raise SystemExit(f"Cosmos local checkpoint is missing: {checkpoint}")

    from cosmos_framework.utils.checkpoint_db import CheckpointDirHf

    def local_download(model: CheckpointDirHf) -> str:
        if model.repository != COSMOS_REPOSITORY:
            raise RuntimeError(
                "offline Cosmos inference rejected an undeclared repository: "
                f"{model.repository}"
            )
        return str(checkpoint)

    # The public CLI's named-checkpoint branch selects the official generator
    # YAML. Its default downloader is replaced at this process boundary so the
    # already verified ModelScope snapshot is used without creating a second
    # Hugging Face cache or making a network request.
    CheckpointDirHf._download = local_download

    from cosmos_framework.scripts.inference import main as cosmos_main

    cosmos_main()


if __name__ == "__main__":
    main()
