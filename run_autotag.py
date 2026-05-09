#!/usr/bin/env python
from ltx2_dataset_builder.config import PipelineConfig
from ltx2_dataset_builder.autotag.face_tag import run_auto_tag

config = PipelineConfig.from_yaml("config.yaml")
run_auto_tag(config, require_confirmed=False)
