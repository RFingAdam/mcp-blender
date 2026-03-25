"""AI 3D generation pipeline orchestrator.

Supports multiple presets with backend routing, component separation
for vehicle modeling, and configurable stage chains.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PipelineStage(Enum):
    GENERATE = "generate"
    IMPORT = "import"
    CLEANUP = "cleanup"
    COMPONENT_SEPARATION = "component_separation"
    UV = "uv"
    TEXTURE = "texture"
    MSFS_PREP = "msfs_prep"


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    stage: PipelineStage
    status: StageStatus = StageStatus.PENDING
    result: dict = field(default_factory=dict)
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class PipelineRun:
    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    params: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)  # stage_name -> StageResult
    current_stage: Optional[str] = None
    object_name: Optional[str] = None  # The Blender object being processed
    mesh_path: Optional[str] = None  # Path to generated mesh file
    component_names: list = field(default_factory=list)  # After component separation

    def to_dict(self):
        return {
            "pipeline_id": self.pipeline_id,
            "object_name": self.object_name,
            "mesh_path": self.mesh_path,
            "current_stage": self.current_stage,
            "component_names": self.component_names,
            "stages": {
                name: {
                    "status": sr.status.value,
                    "result": sr.result,
                    "error": sr.error,
                    "duration_seconds": sr.duration_seconds,
                }
                for name, sr in self.stages.items()
            },
        }


# Preset configurations: stages to run and default backend
PRESET_CONFIGS = {
    "quick": {
        "backend": "stable_fast_3d",
        "stages": [PipelineStage.GENERATE, PipelineStage.IMPORT],
        "description": "Fast 15s preview via SF3D",
    },
    "standard": {
        "backend": "triposg",
        "stages": [
            PipelineStage.GENERATE, PipelineStage.IMPORT,
            PipelineStage.CLEANUP, PipelineStage.UV,
        ],
        "description": "Good single-image quality via TripoSG",
    },
    "multiview_quality": {
        "backend": "multiview",
        "stages": [
            PipelineStage.GENERATE, PipelineStage.IMPORT,
            PipelineStage.CLEANUP, PipelineStage.UV,
        ],
        "description": "Best quality via Zero123Plus + InstantMesh",
    },
    "vehicle_components": {
        "backend": "multiview",
        "stages": [
            PipelineStage.GENERATE, PipelineStage.IMPORT,
            PipelineStage.CLEANUP, PipelineStage.COMPONENT_SEPARATION,
            PipelineStage.UV,
        ],
        "description": "Vehicle with part separation via multi-view",
    },
    "msfs_vehicle": {
        "backend": "multiview",
        "stages": [
            PipelineStage.GENERATE, PipelineStage.IMPORT,
            PipelineStage.CLEANUP, PipelineStage.UV,
            PipelineStage.MSFS_PREP,
        ],
        "description": "MSFS vehicle with LOD/collision via multi-view",
    },
    "msfs_building": {
        "backend": "triposg",
        "stages": [
            PipelineStage.GENERATE, PipelineStage.IMPORT,
            PipelineStage.CLEANUP, PipelineStage.UV,
            PipelineStage.MSFS_PREP,
        ],
        "description": "MSFS building via TripoSG",
    },
    "generic": {
        "backend": "auto",
        "stages": [
            PipelineStage.GENERATE, PipelineStage.IMPORT,
            PipelineStage.CLEANUP, PipelineStage.UV,
        ],
        "description": "Default pipeline with best available backend",
    },
}


# Store active pipeline runs
_pipeline_runs = {}


def run_pipeline(params, handlers):
    """Execute the AI 3D generation pipeline.

    Args:
        params: Pipeline parameters dict
        handlers: Reference to CommandHandlers instance for calling other handlers

    Returns:
        PipelineRun dict with results from each stage
    """
    run = PipelineRun(params=params)
    _pipeline_runs[run.pipeline_id] = run

    preset = params.get("pipeline_preset", "generic")
    preset_config = PRESET_CONFIGS.get(preset, PRESET_CONFIGS["generic"])
    skip = set(params.get("skip_stages", []))
    existing_object = params.get("existing_object")

    # Use preset's backend unless explicitly overridden
    if "backend" not in params or params["backend"] == "auto":
        params["backend"] = preset_config["backend"]

    # Get stages from preset config
    stages_to_run = list(preset_config["stages"])

    # Add texture stage if a texture prompt is provided
    if params.get("texture_prompt") or params.get("prompt"):
        if PipelineStage.TEXTURE not in stages_to_run:
            # Insert texture before MSFS_PREP if present, else append
            if PipelineStage.MSFS_PREP in stages_to_run:
                idx = stages_to_run.index(PipelineStage.MSFS_PREP)
                stages_to_run.insert(idx, PipelineStage.TEXTURE)
            else:
                stages_to_run.append(PipelineStage.TEXTURE)

    # If existing object, skip generate and import
    if existing_object:
        skip.add("generate")
        skip.add("import")
        run.object_name = existing_object

    # Initialize stage results
    for stage in stages_to_run:
        if stage.value in skip:
            run.stages[stage.value] = StageResult(
                stage=stage, status=StageStatus.SKIPPED
            )
        else:
            run.stages[stage.value] = StageResult(stage=stage)

    # Execute stages
    for stage in stages_to_run:
        if stage.value in skip:
            continue

        run.current_stage = stage.value
        sr = run.stages[stage.value]
        sr.status = StageStatus.RUNNING
        start_time = time.time()

        try:
            if stage == PipelineStage.GENERATE:
                result = _run_generate(params, handlers)
                sr.result = result
                run.mesh_path = result.get("mesh_path")

            elif stage == PipelineStage.IMPORT:
                if not run.mesh_path:
                    raise ValueError("No mesh path from generation stage")
                result = handlers._handle_import_file({"filepath": run.mesh_path})
                sr.result = result
                if result.get("imported_objects"):
                    run.object_name = result["imported_objects"][0]

            elif stage == PipelineStage.CLEANUP:
                if not run.object_name:
                    raise ValueError("No object to clean up")
                handlers._handle_ai_mesh_cleanup(
                    {
                        "object_name": run.object_name,
                        "remove_doubles": True,
                        "fix_normals": True,
                        "remove_loose": True,
                    }
                )
                target = int(params.get("target_polycount", 10000))
                stats = handlers._handle_ai_mesh_stats(
                    {"object_name": run.object_name}
                )
                current_faces = stats.get("faces", 0)
                if current_faces > target:
                    ratio = target / current_faces
                    handlers._handle_ai_mesh_decimate(
                        {
                            "object_name": run.object_name,
                            "ratio": max(0.1, min(ratio, 1.0)),
                        }
                    )
                # Fix remaining issues (skip remove_interior_faces -
                # AI-generated meshes often get entirely deleted by it)
                handlers._handle_ai_fix_mesh_issues(
                    {
                        "object_name": run.object_name,
                        "fix_non_manifold": True,
                        "fill_holes": True,
                        "remove_interior_faces": False,
                    }
                )
                sr.result = {"cleanup": "completed", "target_polycount": target}

            elif stage == PipelineStage.COMPONENT_SEPARATION:
                if not run.object_name:
                    raise ValueError("No object for component separation")
                result = handlers._handle_object_separate(
                    {"name": run.object_name, "mode": "LOOSE"}
                )
                separated = result.get("new_objects", [])
                if separated:
                    run.component_names = separated
                else:
                    # Object was a single component - keep it as-is
                    run.component_names = [run.object_name]
                sr.result = {
                    "components": run.component_names,
                    "count": len(run.component_names),
                }

            elif stage == PipelineStage.UV:
                if not run.object_name:
                    raise ValueError("No object for UV unwrap")
                # UV unwrap all components if separation was run
                objects_to_uv = run.component_names if run.component_names else [run.object_name]
                uv_results = []
                for obj_name in objects_to_uv:
                    result = handlers._handle_ai_auto_uv(
                        {"object_name": obj_name, "method": "SMART"}
                    )
                    uv_results.append({"object": obj_name, "result": result})
                    if not result.get("success", True):
                        raise ValueError(
                            f"UV unwrap failed for {obj_name}: {result.get('error', 'unknown')}"
                        )
                sr.result = {"uv_results": uv_results}

            elif stage == PipelineStage.TEXTURE:
                texture_prompt = params.get("texture_prompt") or params.get(
                    "prompt", ""
                )
                if texture_prompt and run.object_name:
                    try:
                        result = handlers._handle_ai_generate_texture_sync(
                            {
                                "object_name": run.object_name,
                                "prompt": texture_prompt,
                                "resolution": int(
                                    params.get("texture_resolution", 1024)
                                ),
                            }
                        )
                        sr.result = result
                    except Exception as tex_err:
                        sr.status = StageStatus.FAILED
                        sr.error = str(tex_err)
                        sr.duration_seconds = time.time() - start_time
                        continue

            elif stage == PipelineStage.MSFS_PREP:
                if not run.object_name:
                    raise ValueError("No object for MSFS prep")
                try:
                    lod_result = handlers._handle_msfs_create_lod_hierarchy(
                        {
                            "base_object_name": run.object_name,
                            "lod_count": 3,
                        }
                    )
                    # Update object name to LOD0 after hierarchy creation
                    lod0_name = f"{run.object_name}_LOD0"
                    import bpy as _bpy
                    if _bpy.data.objects.get(lod0_name):
                        run.object_name = lod0_name
                    handlers._handle_msfs_create_collision_box(
                        {"object_name": run.object_name}
                    )
                    validation = handlers._handle_msfs_validate_for_export(
                        {"object_name": run.object_name}
                    )
                    output_dir = params.get("output_dir")
                    if output_dir:
                        handlers._handle_msfs_export_model(
                            {"output_dir": output_dir}
                        )
                    sr.result = {
                        "lod": lod_result,
                        "validation": validation,
                        "output_dir": output_dir,
                    }
                except Exception as msfs_err:
                    sr.status = StageStatus.FAILED
                    sr.error = str(msfs_err)
                    sr.duration_seconds = time.time() - start_time
                    continue

            sr.status = StageStatus.COMPLETED
            sr.duration_seconds = time.time() - start_time

        except Exception as e:
            sr.status = StageStatus.FAILED
            sr.error = str(e)
            sr.duration_seconds = time.time() - start_time
            # Critical stages stop the pipeline
            if stage in (PipelineStage.GENERATE, PipelineStage.IMPORT):
                break

    run.current_stage = None
    return run.to_dict()


def _run_generate(params, handlers):
    """Run the 3D generation stage."""
    backend = params.get("backend", "auto")
    image_path = params.get("image_path")
    prompt = params.get("prompt", "3D model")
    max_wait = int(params.get("max_wait", 600))

    # If no image, generate a reference image first
    if not image_path and prompt:
        try:
            ref_result = handlers._handle_ai_generate_reference_image(
                {
                    "prompt": prompt,
                    "width": 1024,
                    "height": 1024,
                }
            )
            image_path = ref_result.get("image_path")
        except Exception:
            pass  # Fall through to text-only generation

    gen_params = {
        "prompt": prompt,
        "max_wait": max_wait,
    }
    if image_path:
        gen_params["image_path"] = image_path

    if backend != "auto":
        gen_params["backend"] = backend

    result = handlers._handle_ai_generate_model_sync(gen_params)
    return result


def get_pipeline_status(pipeline_id):
    """Get status of a pipeline run."""
    run = _pipeline_runs.get(pipeline_id)
    if not run:
        return {"error": f"Pipeline {pipeline_id} not found"}
    return run.to_dict()
