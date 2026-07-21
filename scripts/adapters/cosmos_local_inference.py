#!/usr/bin/env python3
"""Run the official Cosmos CLI while resolving its pinned checkpoint locally."""

from __future__ import annotations

import os
from pathlib import Path


COSMOS_REPOSITORY = "nvidia/Cosmos3-Edge"
VAE_REPOSITORY = "Wan-AI/Wan2.2-TI2V-5B"
VAE_REVISION = "921dbaf3f1674a56f47e83fb80a34bac8a8f203e"
VAE_FILENAME = "Wan2.2_VAE.pth"


def main() -> None:
    checkpoint = Path(os.environ["OVERSEAARK_COSMOS_LOCAL_CHECKPOINT"]).resolve()
    if not checkpoint.is_dir():
        raise SystemExit(f"Cosmos local checkpoint is missing: {checkpoint}")
    vae_checkpoint = Path(os.environ["OVERSEAARK_COSMOS_VAE_CHECKPOINT"]).resolve()
    if not vae_checkpoint.is_file():
        raise SystemExit(f"Wan2.2 VAE checkpoint is missing: {vae_checkpoint}")

    from cosmos_framework.utils.checkpoint_db import CheckpointDirHf, CheckpointFileHf

    def local_download(model: CheckpointDirHf) -> str:
        if model.repository != COSMOS_REPOSITORY:
            raise RuntimeError(
                "offline Cosmos inference rejected an undeclared repository: "
                f"{model.repository}"
            )
        return str(checkpoint)

    def local_file_download(model: CheckpointFileHf) -> str:
        identity = (model.repository, model.revision, model.filename)
        expected = (VAE_REPOSITORY, VAE_REVISION, VAE_FILENAME)
        if identity != expected:
            raise RuntimeError(
                "offline Cosmos inference rejected an undeclared file: "
                f"{model.repository}@{model.revision}/{model.filename}"
            )
        return str(vae_checkpoint)

    # The public CLI's named-checkpoint branch selects the official generator
    # YAML. Its default downloader is replaced at this process boundary so the
    # already verified ModelScope snapshot is used without creating a second
    # Hugging Face cache or making a network request.
    CheckpointDirHf._download = local_download
    CheckpointFileHf._download = local_file_download

    from cosmos_framework.scripts.inference import main as cosmos_main

    cosmos_main()


if __name__ == "__main__":
    main()
