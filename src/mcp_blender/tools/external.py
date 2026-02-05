"""External integration tools (Poly Haven, AI model generation)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server

    from ..blender_client import BlenderClient


def register_external_tools(server: "Server", get_client: "callable") -> None:
    """Register external integration tools with the MCP server."""

    # =========================================================================
    # Poly Haven Tools
    # =========================================================================

    @server.call_tool()
    async def blender_polyhaven_search(arguments: dict) -> list:
        """Search Poly Haven for HDRIs, textures, or models."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "polyhaven_search",
            {
                "query": arguments.get("query", ""),
                "asset_type": arguments.get("asset_type"),  # hdris, textures, models
                "categories": arguments.get("categories"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_polyhaven_download(arguments: dict) -> list:
        """Download and apply a Poly Haven asset."""
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "polyhaven_download",
            {
                "asset_id": arguments["asset_id"],
                "resolution": arguments.get("resolution", "2k"),
                "apply_to": arguments.get("apply_to"),  # For textures: material name
            },
        )
        return [{"type": "text", "text": str(result)}]

    # =========================================================================
    # AI Model Generation Tools
    # =========================================================================

    @server.call_tool()
    async def blender_ai_generate_model(arguments: dict) -> list:
        """Generate a 3D model using AI (text-to-3D or image-to-3D).

        Supports multiple backends including Rodin (cloud), Meshy (cloud),
        TripoSR (local), and Hunyuan3D (local). Use blender_ai_list_backends
        to see available backends.

        Args:
            prompt: Text description of the desired 3D model
            image_path: Optional path to input image for image-to-3D
            style: Style modifier (realistic, cartoon, low_poly, sculpture, anime)
            quality: Generation quality (draft, medium, high)
            output_format: Output format (glb, gltf, fbx, obj)
            backend: Specific backend to use (or omit for auto-selection)

        Returns:
            Job ID for tracking generation progress
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_generate_model",
            {
                "prompt": arguments.get("prompt", ""),
                "image_path": arguments.get("image_path"),
                "style": arguments.get("style"),
                "quality": arguments.get("quality", "medium"),
                "output_format": arguments.get("output_format", "glb"),
                "backend": arguments.get("backend"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_model_status(arguments: dict) -> list:
        """Check the status of an AI model generation job.

        Args:
            job_id: The job ID from blender_ai_generate_model
            auto_import: If True, automatically import completed models (default: True)
            backend: Optional backend hint for faster lookup

        Returns:
            Status, progress, and import info if completed
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_model_status",
            {
                "job_id": arguments["job_id"],
                "auto_import": arguments.get("auto_import", True),
                "backend": arguments.get("backend"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    # =========================================================================
    # AI Backend Management Tools
    # =========================================================================

    @server.call_tool()
    async def blender_ai_list_backends(arguments: dict) -> list:
        """List all available AI generation backends.

        Returns information about each backend including:
        - Name and capabilities (text-to-3D, image-to-3D, local/cloud)
        - Availability status
        - Requirements (API key, local installation)

        Args:
            available_only: If True, only show backends ready to use (default: True)

        Returns:
            List of backends with their capabilities and status
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_list_backends",
            {"available_only": arguments.get("available_only", True)},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_set_backend(arguments: dict) -> list:
        """Set the preferred AI backend for generation.

        Args:
            backend: Backend name to use, or None/empty for auto-selection
            prefer_local: If True, prefer local backends over cloud when auto-selecting

        Returns:
            Confirmation with available backends list
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_set_backend",
            {
                "backend": arguments.get("backend"),
                "prefer_local": arguments.get("prefer_local"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_get_backend_info(arguments: dict) -> list:
        """Get detailed information about a specific AI backend.

        Args:
            backend: Name of the backend to query

        Returns:
            Detailed info including capabilities, requirements, supported options
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_get_backend_info",
            {"backend": arguments["backend"]},
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_configure_backend(arguments: dict) -> list:
        """Configure a specific AI backend.

        Args:
            backend: Name of the backend to configure
            config: Configuration dict with keys like:
                - api_key: API key for cloud backends
                - model_path: Local model path
                - device: Device to use (auto, cuda, cpu, mps)
                - enabled: Whether backend is enabled

        Returns:
            Confirmation of configuration
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_configure_backend",
            {
                "backend": arguments["backend"],
                "config": arguments.get("config", {}),
            },
        )
        return [{"type": "text", "text": str(result)}]

    # =========================================================================
    # AI Generation Enhancement Tools
    # =========================================================================

    @server.call_tool()
    async def blender_ai_generate_variations(arguments: dict) -> list:
        """Generate multiple variations of a prompt.

        Useful for exploring different interpretations of a concept.

        Args:
            prompt: Text description of the desired model
            num_variations: Number of variations to generate (default: 3)
            style: Style modifier
            quality: Generation quality
            output_format: Output format
            backend: Specific backend to use

        Returns:
            List of job IDs for each variation
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_generate_variations",
            {
                "prompt": arguments["prompt"],
                "num_variations": arguments.get("num_variations", 3),
                "style": arguments.get("style"),
                "quality": arguments.get("quality", "medium"),
                "output_format": arguments.get("output_format", "glb"),
                "backend": arguments.get("backend"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_cancel_generation(arguments: dict) -> list:
        """Cancel an in-progress generation job.

        Args:
            job_id: The job ID to cancel
            backend: Optional backend hint

        Returns:
            Cancellation status
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_cancel_generation",
            {
                "job_id": arguments["job_id"],
                "backend": arguments.get("backend"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_redo_generation(arguments: dict) -> list:
        """Redo the last generation with optional modifications.

        Args:
            prompt: New prompt (optional, uses last prompt if not provided)
            style: New style (optional)
            quality: New quality (optional)
            output_format: New format (optional)
            backend: Specific backend (optional)

        Returns:
            New job ID for the regeneration
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_redo_generation",
            {
                "prompt": arguments.get("prompt"),
                "style": arguments.get("style"),
                "quality": arguments.get("quality"),
                "output_format": arguments.get("output_format"),
                "backend": arguments.get("backend"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    # =========================================================================
    # Mesh Processing Tools
    # =========================================================================

    @server.call_tool()
    async def blender_ai_mesh_cleanup(arguments: dict) -> list:
        """Clean up a generated mesh by removing doubles, fixing normals, etc.

        Args:
            object_name: Name of the mesh object to clean
            remove_doubles: Remove duplicate vertices (default: True)
            merge_distance: Distance threshold for merging (default: 0.0001)
            fix_normals: Recalculate normals to face outward (default: True)
            remove_loose: Remove loose vertices/edges (default: True)
            remove_degenerate: Remove degenerate geometry (default: True)

        Returns:
            Cleanup statistics (vertices removed, etc.)
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_mesh_cleanup",
            {
                "object_name": arguments["object_name"],
                "remove_doubles": arguments.get("remove_doubles", True),
                "merge_distance": arguments.get("merge_distance", 0.0001),
                "fix_normals": arguments.get("fix_normals", True),
                "remove_loose": arguments.get("remove_loose", True),
                "remove_degenerate": arguments.get("remove_degenerate", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_mesh_decimate(arguments: dict) -> list:
        """Reduce polygon count of a mesh intelligently.

        Args:
            object_name: Name of the mesh object
            ratio: Target ratio of faces to keep (0.0-1.0, default: 0.5)
            method: Decimation method (COLLAPSE, UNSUBDIV, DISSOLVE)
            triangulate: Triangulate before decimating (default: False)
            preserve_uvs: Try to preserve UV seams (default: True)
            vertex_group: Optional vertex group to influence decimation
            invert_vertex_group: Invert vertex group influence

        Returns:
            Decimation statistics (before/after face counts)
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_mesh_decimate",
            {
                "object_name": arguments["object_name"],
                "ratio": arguments.get("ratio", 0.5),
                "method": arguments.get("method", "COLLAPSE"),
                "triangulate": arguments.get("triangulate", False),
                "preserve_uvs": arguments.get("preserve_uvs", True),
                "vertex_group": arguments.get("vertex_group"),
                "invert_vertex_group": arguments.get("invert_vertex_group", False),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_mesh_remesh(arguments: dict) -> list:
        """Retopologize a mesh for better geometry flow.

        Args:
            object_name: Name of the mesh object
            method: Remesh method (VOXEL, QUAD, SHARP, SMOOTH, BLOCKS)
            voxel_size: Voxel size for VOXEL method (default: 0.05)
            octree_depth: Octree depth for other methods (default: 5)
            smooth_normals: Smooth normals after remeshing (default: True)
            apply_smooth: Apply smoothing pass (default: True)
            smooth_factor: Smoothing factor (default: 0.5)
            smooth_iterations: Smoothing iterations (default: 2)

        Returns:
            Remesh statistics
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_mesh_remesh",
            {
                "object_name": arguments["object_name"],
                "method": arguments.get("method", "VOXEL"),
                "voxel_size": arguments.get("voxel_size", 0.05),
                "octree_depth": arguments.get("octree_depth", 5),
                "smooth_normals": arguments.get("smooth_normals", True),
                "apply_smooth": arguments.get("apply_smooth", True),
                "smooth_factor": arguments.get("smooth_factor", 0.5),
                "smooth_iterations": arguments.get("smooth_iterations", 2),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_mesh_optimize(arguments: dict) -> list:
        """Run full optimization pipeline on a mesh.

        Combines cleanup, decimation, UV unwrapping, and normal smoothing.

        Args:
            object_name: Name of the mesh object
            cleanup: Run cleanup pass (default: True)
            decimate: Run decimation (default: True)
            decimate_ratio: Target face ratio for decimation (default: 0.5)
            auto_uv: Generate UVs (default: True)
            smooth_normals: Smooth shade the result (default: True)

        Returns:
            Full optimization results for each step
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_mesh_optimize",
            {
                "object_name": arguments["object_name"],
                "cleanup": arguments.get("cleanup", True),
                "decimate": arguments.get("decimate", True),
                "decimate_ratio": arguments.get("decimate_ratio", 0.5),
                "auto_uv": arguments.get("auto_uv", True),
                "smooth_normals": arguments.get("smooth_normals", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_auto_uv(arguments: dict) -> list:
        """Generate UV maps for a mesh.

        Args:
            object_name: Name of the mesh object
            method: UV projection method (SMART, LIGHTMAP, CUBE, CYLINDER, SPHERE)
            angle_limit: Angle limit for smart project in degrees (default: 66)
            island_margin: Margin between UV islands (default: 0.02)
            area_weight: Area weight for smart project (default: 0.0)
            correct_aspect: Correct for non-square textures (default: True)
            scale_to_bounds: Scale UVs to fit 0-1 space (default: True)
            uv_layer_name: Name for the new UV layer (optional)

        Returns:
            UV generation results including layer name
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_auto_uv",
            {
                "object_name": arguments["object_name"],
                "method": arguments.get("method", "SMART"),
                "angle_limit": arguments.get("angle_limit", 66.0),
                "island_margin": arguments.get("island_margin", 0.02),
                "area_weight": arguments.get("area_weight", 0.0),
                "correct_aspect": arguments.get("correct_aspect", True),
                "scale_to_bounds": arguments.get("scale_to_bounds", True),
                "uv_layer_name": arguments.get("uv_layer_name"),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_fix_mesh_issues(arguments: dict) -> list:
        """Fix common mesh problems automatically.

        Args:
            object_name: Name of the mesh object
            fix_non_manifold: Fix non-manifold geometry (default: True)
            fill_holes: Fill small holes (default: True)
            max_hole_edges: Maximum edges in holes to fill (default: 12)
            fix_normals: Recalculate normals (default: True)
            remove_interior_faces: Remove hidden interior faces (default: True)

        Returns:
            List of fixes applied
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_fix_mesh_issues",
            {
                "object_name": arguments["object_name"],
                "fix_non_manifold": arguments.get("fix_non_manifold", True),
                "fill_holes": arguments.get("fill_holes", True),
                "max_hole_edges": arguments.get("max_hole_edges", 12),
                "fix_normals": arguments.get("fix_normals", True),
                "remove_interior_faces": arguments.get("remove_interior_faces", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_mesh_stats(arguments: dict) -> list:
        """Get detailed statistics about a mesh.

        Args:
            object_name: Name of the mesh object

        Returns:
            Mesh statistics including vertex/face counts, UV info, materials, issues
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_mesh_stats",
            {"object_name": arguments["object_name"]},
        )
        return [{"type": "text", "text": str(result)}]

    # =========================================================================
    # Queue Management Tools
    # =========================================================================

    @server.call_tool()
    async def blender_ai_queue_list(arguments: dict) -> list:
        """List all generation jobs in the queue.

        Args:
            status: Filter by status (pending, processing, completed, failed)
            backend: Filter by backend name
            limit: Maximum number of jobs to return
            include_completed: Include completed jobs (default: True)

        Returns:
            List of jobs with their status and details
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_queue_list",
            {
                "status": arguments.get("status"),
                "backend": arguments.get("backend"),
                "limit": arguments.get("limit"),
                "include_completed": arguments.get("include_completed", True),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_queue_clear(arguments: dict) -> list:
        """Clear completed or failed jobs from the queue.

        Args:
            older_than_hours: Only clear jobs older than this (optional)
            clear_failed: If True, clear only failed jobs (default: False)

        Returns:
            Number of jobs cleared
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_queue_clear",
            {
                "older_than_hours": arguments.get("older_than_hours"),
                "clear_failed": arguments.get("clear_failed", False),
            },
        )
        return [{"type": "text", "text": str(result)}]

    @server.call_tool()
    async def blender_ai_get_history(arguments: dict) -> list:
        """Get generation history with metadata.

        Args:
            limit: Maximum number of entries to return (default: 50)

        Returns:
            History entries with prompts, status, and result info
        """
        client: BlenderClient = await get_client()
        result = await client.send_command(
            "ai_get_history",
            {"limit": arguments.get("limit", 50)},
        )
        return [{"type": "text", "text": str(result)}]
