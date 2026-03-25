"""AI, refinement, and script execution command handlers."""

import contextlib
import io
import json
import tempfile

import bpy

from ..validation import (
    ValidationError,
    require_param,
    validate_enum,
    validate_filepath,
)


class AIHandlersMixin:
    """Mixin for AI, refinement, and script execution handlers."""

    def _handle_polyhaven_search(self, params: dict) -> dict:
        """Search Poly Haven assets."""
        # This will be implemented in the external module
        from ..external.polyhaven import search_polyhaven
        return search_polyhaven(
            query=params.get("query", ""),
            asset_type=params.get("asset_type"),
            categories=params.get("categories"),
        )


    def _handle_polyhaven_download(self, params: dict) -> dict:
        """Download and apply Poly Haven asset."""
        from ..external.polyhaven import download_polyhaven
        return download_polyhaven(
            asset_id=params["asset_id"],
            resolution=params.get("resolution", "2k"),
            apply_to=params.get("apply_to"),
        )


    def _handle_ai_generate_model(self, params: dict) -> dict:
        """Generate 3D model via AI (text-to-3D or image-to-3D)."""
        from ..external.ai_models import generate_model, generate_model_from_image

        # Check if this is image-to-3D or text-to-3D
        image_path = params.get("image_path")
        if image_path:
            return generate_model_from_image(
                image_path=image_path,
                prompt=params.get("prompt"),
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )
        else:
            return generate_model(
                prompt=params["prompt"],
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )


    def _handle_ai_model_status(self, params: dict) -> dict:
        """Check AI model generation status."""
        from ..external.ai_models import check_status
        return check_status(
            job_id=params["job_id"],
            auto_import=params.get("auto_import", True),
        )


    def _handle_ai_generate_model_sync(self, params: dict) -> dict:
        """Generate 3D model and poll until complete (synchronous)."""
        from ..external.ai_models import (
            generate_model,
            generate_model_from_image,
            poll_until_complete,
        )

        # Generate the model (text-to-3D or image-to-3D)
        image_path = params.get("image_path")
        if image_path:
            result = generate_model_from_image(
                image_path=image_path,
                prompt=params.get("prompt"),
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )
        else:
            result = generate_model(
                prompt=params.get("prompt", ""),
                style=params.get("style"),
                quality=params.get("quality", "medium"),
                output_format=params.get("output_format", "glb"),
            )

        if not result.get("success") or not result.get("job_id"):
            return result

        # Poll until complete
        max_wait = params.get("max_wait", 300)
        auto_import = params.get("auto_import", True)
        return poll_until_complete(
            job_id=result["job_id"],
            max_wait=max_wait,
            auto_import=auto_import,
        )

    # ========== Texture Generation Handlers ==========


    def _handle_ai_generate_texture(self, params: dict) -> dict:
        """Generate PBR texture set from text, optionally apply to object."""
        from ..external.ai_models import generate_texture

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="pbr_texture",
            object_name=params.get("object_name"),
            auto_apply=params.get("auto_apply", True),
            texture_types=params.get("texture_types"),
            width=params.get("resolution", 1024),
            height=params.get("resolution", 1024),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark, text, logo"),
            seed=params.get("seed"),
        )


    def _handle_ai_generate_texture_sync(self, params: dict) -> dict:
        """Generate PBR texture and poll until complete (synchronous)."""
        from ..external.ai_models import generate_texture, poll_until_complete

        result = generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="pbr_texture",
            object_name=params.get("object_name"),
            auto_apply=params.get("auto_apply", True),
            texture_types=params.get("texture_types"),
            width=params.get("resolution", 1024),
            height=params.get("resolution", 1024),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark, text, logo"),
            seed=params.get("seed"),
        )

        if not result.get("success") or not result.get("job_id"):
            return result

        timeout = params.get("timeout", 300)
        return poll_until_complete(
            job_id=result["job_id"],
            max_wait=timeout,
            auto_import=False,
        )


    def _handle_ai_generate_reference_image(self, params: dict) -> dict:
        """Generate concept art / reference image from text."""
        from ..external.ai_models import generate_texture

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="reference_image",
            width=params.get("resolution", 1024),
            height=params.get("resolution", 1024),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark, text, logo"),
            seed=params.get("seed"),
        )


    def _handle_ai_inpaint_texture(self, params: dict) -> dict:
        """Inpaint a region of an existing texture."""
        from ..external.ai_models import generate_texture

        image_path = require_param(params, "image_path", str)
        mask_path = require_param(params, "mask_path", str)
        validate_filepath(image_path, must_exist=True)
        validate_filepath(mask_path, must_exist=True)

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="inpaint",
            image_path=image_path,
            mask_path=mask_path,
            denoise=params.get("strength", 0.85),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark"),
            seed=params.get("seed"),
        )


    def _handle_ai_texture_from_render(self, params: dict) -> dict:
        """Generate texture from depth/normal render via ControlNet."""
        from ..external.ai_models import generate_texture

        object_name = require_param(params, "object_name", str)
        control_type = params.get("control_type", "depth")
        validate_enum(control_type, "control_type", ["depth", "normal"])

        # Render the object to get control image
        render_path = self._render_control_image(object_name, control_type)
        if not render_path:
            return {"success": False, "error": f"Failed to render {control_type} pass for '{object_name}'"}

        return generate_texture(
            prompt=require_param(params, "prompt", str),
            workflow_type="controlnet_texture",
            object_name=object_name,
            auto_apply=params.get("auto_apply", True),
            image_path=render_path,
            controlnet_strength=params.get("controlnet_strength", 0.85),
            negative_prompt=params.get("negative_prompt", "blurry, low quality, watermark"),
            seed=params.get("seed"),
        )


    def _render_control_image(self, object_name: str, control_type: str) -> str | None:
        """Render a depth or normal pass of an object for ControlNet input."""
        obj = bpy.data.objects.get(object_name)
        if not obj:
            return None

        scene = bpy.context.scene
        render = scene.render

        # Save current settings
        old_engine = render.engine
        old_film = render.film_transparent
        old_filepath = render.filepath
        old_res_x = render.resolution_x
        old_res_y = render.resolution_y

        try:
            render.engine = "BLENDER_EEVEE_NEXT"
            render.film_transparent = True
            render.resolution_x = 1024
            render.resolution_y = 1024

            output_path = tempfile.mktemp(suffix=".png", prefix=f"control_{control_type}_")
            render.filepath = output_path

            # Enable the appropriate render pass via view layer
            scene.use_nodes = True
            view_layer = bpy.context.view_layer
            if control_type == "depth":
                view_layer.use_pass_z = True
            elif control_type == "normal":
                view_layer.use_pass_normal = True

            bpy.ops.render.render(write_still=True)
            return output_path

        except Exception:
            return None
        finally:
            render.engine = old_engine
            render.film_transparent = old_film
            render.filepath = old_filepath
            render.resolution_x = old_res_x
            render.resolution_y = old_res_y

    # ========== New AI Backend Management Handlers ==========


    def _handle_ai_list_backends(self, params: dict) -> dict:
        """List all available AI generation backends."""
        from ..external.ai_models import list_backends
        return list_backends(
            available_only=params.get("available_only", True),
        )


    def _handle_ai_set_backend(self, params: dict) -> dict:
        """Set the preferred AI backend."""
        from ..external.ai_models import set_preferred_backend
        return set_preferred_backend(
            backend=params.get("backend"),
            prefer_local=params.get("prefer_local"),
        )


    def _handle_ai_get_backend_info(self, params: dict) -> dict:
        """Get detailed information about a specific backend."""
        from ..external.ai_models import get_backend_info
        return get_backend_info(
            backend=require_param(params, "backend", str),
        )


    def _handle_ai_configure_backend(self, params: dict) -> dict:
        """Configure a specific AI backend."""
        from ..external.ai_models import configure_backend
        return configure_backend(
            backend=require_param(params, "backend", str),
            config=params.get("config", {}),
        )

    # ========== New AI Generation Enhancement Handlers ==========


    def _handle_ai_generate_variations(self, params: dict) -> dict:
        """Generate multiple variations of a prompt."""
        from ..external.ai_models import generate_model

        prompt = require_param(params, "prompt", str)
        num_variations = params.get("num_variations", 3)
        style = params.get("style")
        quality = params.get("quality", "medium")
        output_format = params.get("output_format", "glb")
        backend = params.get("backend")

        results = []
        for i in range(num_variations):
            result = generate_model(
                prompt=prompt,
                style=style,
                quality=quality,
                output_format=output_format,
                backend=backend,
            )
            results.append({
                "variation": i + 1,
                **result,
            })

        return {
            "success": True,
            "prompt": prompt,
            "num_variations": num_variations,
            "results": results,
        }


    def _handle_ai_cancel_generation(self, params: dict) -> dict:
        """Cancel an in-progress generation job."""
        from ..external.ai_models import cancel_generation
        return cancel_generation(
            job_id=require_param(params, "job_id", str),
            backend=params.get("backend"),
        )


    def _handle_ai_redo_generation(self, params: dict) -> dict:
        """Redo the last generation with optional modifications."""
        from ..external.ai_models import generate_model, generate_model_from_image
        from ..external.job_queue import get_job_queue

        queue = get_job_queue()
        last_job = queue.get_last_job(backend=params.get("backend"))

        if not last_job:
            return {"success": False, "error": "No previous generation found"}

        # Allow overriding parameters
        prompt = params.get("prompt", last_job.prompt)
        style = params.get("style", last_job.style)
        quality = params.get("quality", last_job.quality)
        output_format = params.get("output_format", last_job.output_format)
        backend = params.get("backend", last_job.backend)

        if last_job.image_path:
            return generate_model_from_image(
                image_path=last_job.image_path,
                prompt=prompt,
                style=style,
                quality=quality,
                output_format=output_format,
                backend=backend if backend != "auto" else None,
            )
        else:
            return generate_model(
                prompt=prompt,
                style=style,
                quality=quality,
                output_format=output_format,
                backend=backend if backend != "auto" else None,
            )

    # ========== Mesh Processing Handlers ==========


    def _handle_ai_mesh_cleanup(self, params: dict) -> dict:
        """Clean up a generated mesh."""
        from ..external.mesh_processing import cleanup_mesh
        return cleanup_mesh(
            object_name=require_param(params, "object_name", str),
            remove_doubles=params.get("remove_doubles", True),
            merge_distance=params.get("merge_distance", 0.0001),
            fix_normals=params.get("fix_normals", True),
            remove_loose=params.get("remove_loose", True),
            remove_degenerate=params.get("remove_degenerate", True),
        )


    def _handle_ai_mesh_decimate(self, params: dict) -> dict:
        """Reduce polygon count of a mesh."""
        from ..external.mesh_processing import decimate_mesh
        return decimate_mesh(
            object_name=require_param(params, "object_name", str),
            ratio=params.get("ratio", 0.5),
            method=params.get("method", "COLLAPSE"),
            triangulate=params.get("triangulate", False),
            preserve_uvs=params.get("preserve_uvs", True),
            vertex_group=params.get("vertex_group"),
            invert_vertex_group=params.get("invert_vertex_group", False),
        )


    def _handle_ai_mesh_remesh(self, params: dict) -> dict:
        """Retopologize a mesh."""
        from ..external.mesh_processing import remesh_object
        return remesh_object(
            object_name=require_param(params, "object_name", str),
            method=params.get("method", "VOXEL"),
            voxel_size=params.get("voxel_size", 0.05),
            octree_depth=params.get("octree_depth", 5),
            smooth_normals=params.get("smooth_normals", True),
            apply_smooth=params.get("apply_smooth", True),
            smooth_factor=params.get("smooth_factor", 0.5),
            smooth_iterations=params.get("smooth_iterations", 2),
        )


    def _handle_ai_mesh_optimize(self, params: dict) -> dict:
        """Run full optimization pipeline on a mesh."""
        from ..external.mesh_processing import optimize_mesh
        return optimize_mesh(
            object_name=require_param(params, "object_name", str),
            cleanup=params.get("cleanup", True),
            decimate=params.get("decimate", True),
            decimate_ratio=params.get("decimate_ratio", 0.5),
            auto_uv=params.get("auto_uv", True),
            smooth_normals=params.get("smooth_normals", True),
        )


    def _handle_ai_auto_uv(self, params: dict) -> dict:
        """Generate UV maps for a mesh."""
        from ..external.mesh_processing import auto_uv_unwrap
        return auto_uv_unwrap(
            object_name=require_param(params, "object_name", str),
            method=params.get("method", "SMART"),
            angle_limit=params.get("angle_limit", 66.0),
            island_margin=params.get("island_margin", 0.02),
            area_weight=params.get("area_weight", 0.0),
            correct_aspect=params.get("correct_aspect", True),
            scale_to_bounds=params.get("scale_to_bounds", True),
            uv_layer_name=params.get("uv_layer_name"),
        )


    def _handle_ai_fix_mesh_issues(self, params: dict) -> dict:
        """Fix common mesh problems."""
        from ..external.mesh_processing import fix_mesh_issues
        return fix_mesh_issues(
            object_name=require_param(params, "object_name", str),
            fix_non_manifold=params.get("fix_non_manifold", True),
            fill_holes=params.get("fill_holes", True),
            max_hole_edges=params.get("max_hole_edges", 12),
            fix_normals=params.get("fix_normals", True),
            remove_interior_faces=params.get("remove_interior_faces", True),
        )


    def _handle_ai_mesh_stats(self, params: dict) -> dict:
        """Get detailed statistics about a mesh."""
        from ..external.mesh_processing import get_mesh_stats
        return get_mesh_stats(
            object_name=require_param(params, "object_name", str),
        )

    # ========== AI Backend Probing Handlers ==========


    def _handle_ai_probe_backends(self, params: dict) -> dict:
        """Probe ComfyUI and report available 3D generation nodes, GPU info, and queue status."""
        import urllib.error
        import urllib.request

        # Default 3D generation node classes to check
        default_nodes = [
            "[Comfy3D] Load SF3D Model",
            "[Comfy3D] StableFast3D",
            "[Comfy3D] Load TripoSR Model",
            "[Comfy3D] TripoSG I23D Model",
            "[Comfy3D] Load InstantMesh Reconstruction Model",
            "[Comfy3D] Zero123Plus Diffusion Model",
            "[Comfy3D] Load Hunyuan3D V2 ShapeGen Pipeline",
            "[Comfy3D] Load Convolutional Reconstruction Model",
        ]

        check_nodes = params.get("check_nodes") or default_nodes

        # Get ComfyUI host from backend manager
        comfyui_host = "http://10.27.27.10:8188"
        try:
            from ..external.ai_backends import get_backend_manager
            manager = get_backend_manager()
            if "comfyui" in manager._backends:
                comfyui_host = manager._backends["comfyui"]._get_host()
        except Exception:
            pass

        result = {
            "success": True,
            "comfyui_host": comfyui_host,
            "comfyui_reachable": False,
            "available_nodes": {},
            "gpu_info": None,
            "queue_status": None,
        }

        # Check ComfyUI connectivity and probe nodes
        try:
            # Fetch full object_info to check node availability
            req = urllib.request.Request(f"{comfyui_host}/object_info")
            with urllib.request.urlopen(req, timeout=10) as response:
                object_info = json.loads(response.read().decode())
            result["comfyui_reachable"] = True

            # Check each requested node
            for node_class in check_nodes:
                result["available_nodes"][node_class] = node_class in object_info
        except urllib.error.URLError as e:
            result["comfyui_reachable"] = False
            result["error"] = f"Cannot connect to ComfyUI at {comfyui_host}: {e}"
            return result
        except Exception as e:
            result["comfyui_reachable"] = False
            result["error"] = f"Error probing ComfyUI: {e}"
            return result

        # Get GPU / system stats
        try:
            req = urllib.request.Request(f"{comfyui_host}/system_stats")
            with urllib.request.urlopen(req, timeout=5) as response:
                system_stats = json.loads(response.read().decode())

            gpu_info = {}
            devices = system_stats.get("devices", [])
            if devices:
                for i, device in enumerate(devices):
                    gpu_info[f"gpu_{i}"] = {
                        "name": device.get("name", "unknown"),
                        "type": device.get("type", "unknown"),
                        "vram_total_mb": round(device.get("vram_total", 0) / (1024 * 1024), 1),
                        "vram_free_mb": round(device.get("vram_free", 0) / (1024 * 1024), 1),
                        "torch_vram_total_mb": round(device.get("torch_vram_total", 0) / (1024 * 1024), 1),
                        "torch_vram_free_mb": round(device.get("torch_vram_free", 0) / (1024 * 1024), 1),
                    }
            result["gpu_info"] = gpu_info
        except Exception as e:
            result["gpu_info"] = {"error": str(e)}

        # Get queue status
        try:
            req = urllib.request.Request(f"{comfyui_host}/queue")
            with urllib.request.urlopen(req, timeout=5) as response:
                queue_data = json.loads(response.read().decode())

            result["queue_status"] = {
                "queue_running": len(queue_data.get("queue_running", [])),
                "queue_pending": len(queue_data.get("queue_pending", [])),
            }
        except Exception as e:
            result["queue_status"] = {"error": str(e)}

        # Summarize available 3D generation capabilities
        available_models = [
            node for node, available in result["available_nodes"].items() if available
        ]
        result["summary"] = {
            "total_nodes_checked": len(check_nodes),
            "nodes_available": len(available_models),
            "available_model_names": available_models,
        }

        return result

    # ========== Queue Management Handlers ==========


    def _handle_ai_queue_list(self, params: dict) -> dict:
        """List all generation jobs."""
        from ..external.job_queue import get_job_queue

        queue = get_job_queue()
        jobs = queue.list_jobs(
            status=params.get("status"),
            backend=params.get("backend"),
            limit=params.get("limit"),
            include_completed=params.get("include_completed", True),
        )

        return {
            "success": True,
            "jobs": [job.to_dict() for job in jobs],
            "count": len(jobs),
        }


    def _handle_ai_queue_clear(self, params: dict) -> dict:
        """Clear completed or failed jobs from the queue."""
        from ..external.job_queue import get_job_queue

        queue = get_job_queue()

        if params.get("clear_failed", False):
            cleared = queue.clear_failed()
            clear_type = "failed"
        else:
            cleared = queue.clear_completed(
                older_than_hours=params.get("older_than_hours"),
            )
            clear_type = "completed"

        return {
            "success": True,
            "cleared": cleared,
            "type": clear_type,
        }


    def _handle_ai_get_history(self, params: dict) -> dict:
        """Get generation history."""
        from ..external.ai_models import get_generation_history
        return get_generation_history(
            limit=params.get("limit", 50),
        )

    # ========== MSFS Content Creation Handlers ==========


    def _handle_execute_script(self, params: dict) -> dict:
        """Execute arbitrary Python script in Blender's context.

        Enables real mesh modeling via bmesh, mathutils, and full Blender API access.
        """
        script = require_param(params, "script", str)

        # Push undo so user can Ctrl+Z
        bpy.ops.ed.undo_push(message="MCP Execute Script")

        # Capture stdout/stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Pre-loaded namespace for script execution
        exec_namespace = {"bpy": bpy, "__builtins__": __builtins__}

        try:
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                exec(script, exec_namespace)  # noqa: S102

            stdout_str = stdout_capture.getvalue()
            stderr_str = stderr_capture.getvalue()

            # Cap output at 64KB
            max_output = 65536
            if len(stdout_str) > max_output:
                stdout_str = stdout_str[:max_output] + "\n... (truncated)"
            if len(stderr_str) > max_output:
                stderr_str = stderr_str[:max_output] + "\n... (truncated)"

            # Check for a 'result' variable set by the script
            script_result = exec_namespace.get("result")
            result_data = None
            if script_result is not None:
                try:
                    import json
                    json.dumps(script_result)
                    result_data = script_result
                except (TypeError, ValueError):
                    result_data = str(script_result)

            return {
                "success": True,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "error": None,
                "result": result_data,
            }

        except Exception as e:
            stdout_str = stdout_capture.getvalue()
            stderr_str = stderr_capture.getvalue()
            return {
                "success": False,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "error": f"{type(e).__name__}: {e}",
                "result": None,
            }

    # ========== Multi-Angle Rendering Handler ==========


    def _handle_analyze_viewport(self, params: dict) -> dict:
        """Render multi-angle views and analyze with Ollama vision model."""
        object_name = params.get("object_name")
        reference_image = params.get("reference_image")
        prompt = params.get("prompt", "Analyze this 3D model render for quality and accuracy.")
        resolution = params.get("resolution", [512, 512])

        # Render multi-angle views
        render_result = self._handle_render_multi_angle({
            "object_name": object_name,
            "resolution": resolution,
        })

        if not render_result.get("success"):
            return render_result

        render_paths = render_result["renders"]

        # Send to Ollama vision for analysis
        try:
            from ..external.ai_backends.base import BackendConfig
            from ..external.ai_backends.ollama_vision import OllamaVisionBackend

            config = BackendConfig(
                enabled=True,
                extra={
                    "host": params.get("ollama_host", "http://10.27.27.10:11434"),
                    "model": params.get("ollama_model", "llama3.2-vision:11b"),
                },
            )
            backend = OllamaVisionBackend(config)

            analysis = backend.analyze_for_refinement(
                image_paths=list(render_paths.values()),
                reference_image=reference_image,
                prompt=prompt,
            )
        except Exception as e:
            analysis = {
                "success": False,
                "error": f"Vision analysis failed: {e}",
            }

        return {
            "success": True,
            "renders": render_paths,
            "analysis": analysis,
            "output_dir": render_result["output_dir"],
        }

    # ========== AI Evaluation & Self-Refinement Handlers ==========


    def _handle_ai_evaluate(self, params: dict) -> dict:
        """Evaluate any render/output using Ollama vision."""
        from ..external.ai_models import evaluate_output

        render_path = require_param(params, "render_path", str)
        category = params.get("category", "model")
        reference_image = params.get("reference_image")
        prompt = params.get("prompt", "")

        if category not in ("model", "texture", "animation"):
            raise ValidationError(f"Invalid category: {category}. Must be model, texture, or animation")

        result = evaluate_output(
            render_path=render_path,
            category=category,
            reference_image=reference_image,
            prompt=prompt,
            ollama_host=params.get("ollama_host", "http://10.27.27.10:11434"),
            ollama_model=params.get("ollama_model", "llama3.2-vision:11b"),
        )

        return result


    def _handle_ai_refine(self, params: dict) -> dict:
        """Run one iteration of AI self-refinement loop."""
        from ..external.ai_models import refine_with_feedback

        object_name = require_param(params, "object_name", str)
        prompt = require_param(params, "prompt", str)
        category = params.get("category", "model")
        max_iterations = params.get("max_iterations", 5)
        quality_threshold = params.get("quality_threshold", 0.85)
        materials = params.get("materials")

        if category not in ("model", "texture", "animation"):
            raise ValidationError(f"Invalid category: {category}. Must be model, texture, or animation")

        result = refine_with_feedback(
            object_name=object_name,
            prompt=prompt,
            category=category,
            max_iterations=max_iterations,
            quality_threshold=quality_threshold,
            materials=materials,
            ollama_host=params.get("ollama_host", "http://10.27.27.10:11434"),
            ollama_model=params.get("ollama_model", "llama3.2-vision:11b"),
        )

        return result

    # ========== Refinement Iteration Handler ==========


    def _handle_refine_iteration(self, params: dict) -> dict:
        """Run one iteration of the refinement feedback loop."""
        object_name = params.get("object_name")
        reference_image = params.get("reference_image")
        prompt = params.get("prompt", "Evaluate this 3D model for geometric accuracy and quality.")
        iteration = params.get("iteration", 0)
        previous_score = params.get("previous_score", 0.0)
        max_iterations = params.get("max_iterations", 10)

        # Analyze current state
        analysis_result = self._handle_analyze_viewport({
            "object_name": object_name,
            "reference_image": reference_image,
            "prompt": prompt,
        })

        if not analysis_result.get("success"):
            return analysis_result

        analysis = analysis_result.get("analysis", {})
        score = analysis.get("overall_quality", 0.0)
        score_delta = score - previous_score

        # Check convergence
        converged = False
        convergence_reason = None

        if score >= 0.85:
            converged = True
            convergence_reason = f"Quality threshold reached: {score:.2f} >= 0.85"
        elif iteration >= 2 and abs(score_delta) < 0.02:
            converged = True
            convergence_reason = f"Score plateau: delta {score_delta:.3f} < 0.02"
        elif iteration >= max_iterations:
            converged = True
            convergence_reason = f"Max iterations reached: {iteration} >= {max_iterations}"

        return {
            "success": True,
            "iteration": iteration,
            "converged": converged,
            "convergence_reason": convergence_reason,
            "score": score,
            "score_delta": score_delta,
            "analysis": analysis,
            "render_paths": analysis_result.get("renders", {}),
        }

    # ========== Refinement Session Management Handlers ==========


    def _handle_refine_create_session(self, params: dict) -> dict:
        """Create a new refinement session."""
        from ..external.refinement import get_refinement_manager

        manager = get_refinement_manager()
        session = manager.create_session(
            object_name=require_param(params, "object_name", str),
            reference_image=params.get("reference_image"),
            prompt=params.get("prompt", ""),
        )
        return {
            "success": True,
            "session_id": session.session_id,
            "object_name": session.object_name,
            "status": session.status,
        }


    def _handle_refine_get_session(self, params: dict) -> dict:
        """Get refinement session details."""
        from ..external.refinement import get_refinement_manager

        manager = get_refinement_manager()
        session = manager.get_session(
            require_param(params, "session_id", str),
        )

        if session is None:
            return {"success": False, "error": "Session not found"}

        return {
            "success": True,
            "session_id": session.session_id,
            "object_name": session.object_name,
            "reference_image": session.reference_image,
            "status": session.status,
            "iterations": [
                {
                    "iteration": it.iteration,
                    "score": it.score,
                    "render_paths": it.render_paths,
                }
                for it in session.iterations
            ],
            "iteration_count": len(session.iterations),
        }


    def _handle_refine_list_sessions(self, params: dict) -> dict:
        """List all refinement sessions."""
        from ..external.refinement import get_refinement_manager

        manager = get_refinement_manager()
        sessions = manager.list_sessions()

        return {
            "success": True,
            "sessions": [
                {
                    "session_id": s.session_id,
                    "object_name": s.object_name,
                    "status": s.status,
                    "iteration_count": len(s.iterations),
                }
                for s in sessions
            ],
            "count": len(sessions),
        }

    # ========== AI Pipeline Handlers ==========


    def _handle_ai_pipeline_generate(self, params: dict) -> dict:
        """Run the full AI 3D generation pipeline."""
        from ..external.pipeline import run_pipeline

        return run_pipeline(params, self)


    def _handle_ai_pipeline_status(self, params: dict) -> dict:
        """Get status of a pipeline run."""
        from ..external.pipeline import get_pipeline_status

        return get_pipeline_status(params.get("pipeline_id", ""))

    # ========== Sculpting Handlers ==========

