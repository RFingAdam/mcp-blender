"""AI-assisted livery transfer between aircraft."""

import base64
import os
from pathlib import Path
from typing import Any

import bpy

# Design element types that can be detected/transferred
DESIGN_ELEMENTS = {
    "cheatline": {
        "description": "Horizontal stripe along fuselage",
        "detection_hints": ["horizontal stripe", "window line", "belt line"],
        "transfer_method": "path_mapping",
    },
    "tail_design": {
        "description": "Vertical stabilizer artwork",
        "detection_hints": ["tail logo", "vertical stabilizer", "fin"],
        "transfer_method": "region_mapping",
    },
    "fuselage_logo": {
        "description": "Main fuselage logo/branding",
        "detection_hints": ["company logo", "airline name", "branding"],
        "transfer_method": "region_mapping",
    },
    "engine_nacelle": {
        "description": "Engine housing livery",
        "detection_hints": ["engine", "nacelle", "cowling"],
        "transfer_method": "region_mapping",
    },
    "belly_color": {
        "description": "Underside color scheme",
        "detection_hints": ["belly", "underside", "lower fuselage"],
        "transfer_method": "color_fill",
    },
    "winglet": {
        "description": "Wing tip device design",
        "detection_hints": ["winglet", "sharklet", "wing tip"],
        "transfer_method": "region_mapping",
    },
    "registration": {
        "description": "Aircraft registration text",
        "detection_hints": ["registration", "tail number", "N-number"],
        "transfer_method": "text_placement",
    },
    "flag": {
        "description": "National flag placement",
        "detection_hints": ["flag", "national colors"],
        "transfer_method": "decal_placement",
    },
}


def analyze_livery(
    image_path: str,
    aircraft_type: str | None = None,
) -> dict[str, Any]:
    """Analyze a livery image to extract design elements.

    Uses image analysis to identify:
    - Color palette
    - Stripe/cheatline patterns
    - Logo positions
    - Design element locations

    Args:
        image_path: Path to livery image (texture or photo)
        aircraft_type: Optional aircraft type for context

    Returns:
        Dictionary with analysis results
    """
    path = Path(image_path)
    if not path.exists():
        return {"error": f"Image not found: {image_path}"}

    # Load image for analysis
    img = bpy.data.images.load(str(path))
    width, height = img.size
    pixels = list(img.pixels)

    # Extract color palette
    colors = _extract_dominant_colors(pixels, width, height)

    # Analyze regions
    regions = _analyze_image_regions(pixels, width, height)

    # Detect design elements
    elements = _detect_design_elements(pixels, width, height, colors)

    # Clean up
    bpy.data.images.remove(img)

    result = {
        "image": str(path),
        "size": [width, height],
        "color_palette": colors,
        "detected_elements": elements,
        "regions": regions,
    }

    if aircraft_type:
        result["aircraft_type"] = aircraft_type

    # Include base64 for potential AI analysis
    with open(path, "rb") as f:
        result["image_base64"] = base64.b64encode(f.read()).decode("utf-8")

    return result


def _extract_dominant_colors(
    pixels: list,
    width: int,
    height: int,
    num_colors: int = 8,
) -> list[dict]:
    """Extract dominant colors from pixel data."""
    from collections import Counter

    # Sample pixels (every 10th pixel for performance)
    sample_colors = []
    for i in range(0, len(pixels), 40):  # Skip by 40 (10 pixels * 4 RGBA channels)
        if i + 3 < len(pixels):
            r = int(pixels[i] * 255)
            g = int(pixels[i + 1] * 255)
            b = int(pixels[i + 2] * 255)
            # Quantize to reduce unique colors
            r = (r // 16) * 16
            g = (g // 16) * 16
            b = (b // 16) * 16
            sample_colors.append((r, g, b))

    # Count occurrences
    color_counts = Counter(sample_colors)
    top_colors = color_counts.most_common(num_colors)

    result = []
    for (r, g, b), count in top_colors:
        percentage = (count / len(sample_colors)) * 100
        result.append({
            "rgb": [r, g, b],
            "hex": "#{:02x}{:02x}{:02x}".format(r, g, b),
            "percentage": round(percentage, 1),
            "rgba_normalized": [r / 255, g / 255, b / 255, 1.0],
        })

    return result


def _analyze_image_regions(
    pixels: list,
    width: int,
    height: int,
) -> dict:
    """Analyze image regions for design elements."""
    # Divide image into regions
    regions = {
        "top": {"y_start": 0, "y_end": height // 3},
        "middle": {"y_start": height // 3, "y_end": 2 * height // 3},
        "bottom": {"y_start": 2 * height // 3, "y_end": height},
        "left": {"x_start": 0, "x_end": width // 3},
        "center": {"x_start": width // 3, "x_end": 2 * width // 3},
        "right": {"x_start": 2 * width // 3, "x_end": width},
    }

    # Analyze each region's dominant color
    for region_name, bounds in regions.items():
        region_colors = []
        y_start = bounds.get("y_start", 0)
        y_end = bounds.get("y_end", height)
        x_start = bounds.get("x_start", 0)
        x_end = bounds.get("x_end", width)

        # Sample region
        for y in range(y_start, y_end, 20):
            for x in range(x_start, x_end, 20):
                idx = (y * width + x) * 4
                if idx + 3 < len(pixels):
                    r = int(pixels[idx] * 255)
                    g = int(pixels[idx + 1] * 255)
                    b = int(pixels[idx + 2] * 255)
                    region_colors.append((r, g, b))

        if region_colors:
            # Calculate average color
            avg_r = sum(c[0] for c in region_colors) // len(region_colors)
            avg_g = sum(c[1] for c in region_colors) // len(region_colors)
            avg_b = sum(c[2] for c in region_colors) // len(region_colors)
            regions[region_name]["average_color"] = {
                "rgb": [avg_r, avg_g, avg_b],
                "hex": "#{:02x}{:02x}{:02x}".format(avg_r, avg_g, avg_b),
            }

    return regions


def _detect_design_elements(
    pixels: list,
    width: int,
    height: int,
    colors: list,
) -> list[dict]:
    """Detect livery design elements."""
    elements = []

    # Detect horizontal stripes (cheatlines)
    stripe_rows = _detect_horizontal_stripes(pixels, width, height)
    if stripe_rows:
        elements.append({
            "type": "cheatline",
            "confidence": 0.8,
            "position": {
                "y_normalized": stripe_rows[0] / height,
                "thickness_normalized": len(stripe_rows) / height,
            },
            "description": f"Horizontal stripe detected at ~{int(stripe_rows[0] / height * 100)}% from top",
        })

    # Detect if belly is different color (common in liveries)
    bottom_region_y = int(height * 0.7)
    top_region_y = int(height * 0.3)

    bottom_avg = _get_region_average(pixels, width, 0, width, bottom_region_y, height)
    top_avg = _get_region_average(pixels, width, 0, width, 0, top_region_y)

    if bottom_avg and top_avg:
        color_diff = sum(abs(b - t) for b, t in zip(bottom_avg, top_avg))
        if color_diff > 100:  # Significant color difference
            elements.append({
                "type": "belly_color",
                "confidence": 0.7,
                "colors": {
                    "upper": {"rgb": list(top_avg)},
                    "lower": {"rgb": list(bottom_avg)},
                },
                "description": "Different belly color detected",
            })

    return elements


def _detect_horizontal_stripes(
    pixels: list,
    width: int,
    height: int,
    threshold: int = 50,
) -> list[int]:
    """Detect horizontal stripe patterns in the image."""
    stripe_rows = []
    prev_row_avg = None

    for y in range(0, height, 5):  # Sample every 5 rows
        row_colors = []
        for x in range(0, width, 10):
            idx = (y * width + x) * 4
            if idx + 2 < len(pixels):
                row_colors.append((
                    int(pixels[idx] * 255),
                    int(pixels[idx + 1] * 255),
                    int(pixels[idx + 2] * 255),
                ))

        if row_colors:
            avg = (
                sum(c[0] for c in row_colors) // len(row_colors),
                sum(c[1] for c in row_colors) // len(row_colors),
                sum(c[2] for c in row_colors) // len(row_colors),
            )

            if prev_row_avg:
                diff = sum(abs(a - b) for a, b in zip(avg, prev_row_avg))
                if diff > threshold:
                    stripe_rows.append(y)

            prev_row_avg = avg

    return stripe_rows


def _get_region_average(
    pixels: list,
    width: int,
    x_start: int,
    x_end: int,
    y_start: int,
    y_end: int,
) -> tuple[int, int, int] | None:
    """Get average color of a region."""
    colors = []
    for y in range(y_start, y_end, 10):
        for x in range(x_start, x_end, 10):
            idx = (y * width + x) * 4
            if idx + 2 < len(pixels):
                colors.append((
                    int(pixels[idx] * 255),
                    int(pixels[idx + 1] * 255),
                    int(pixels[idx + 2] * 255),
                ))

    if colors:
        return (
            sum(c[0] for c in colors) // len(colors),
            sum(c[1] for c in colors) // len(colors),
            sum(c[2] for c in colors) // len(colors),
        )
    return None


def extract_color_palette(
    image_path: str,
    num_colors: int = 8,
) -> dict[str, Any]:
    """Extract color palette from a livery image.

    Args:
        image_path: Path to image
        num_colors: Number of colors to extract

    Returns:
        Dictionary with color palette
    """
    path = Path(image_path)
    if not path.exists():
        return {"error": f"Image not found: {image_path}"}

    img = bpy.data.images.load(str(path))
    width, height = img.size
    pixels = list(img.pixels)

    colors = _extract_dominant_colors(pixels, width, height, num_colors)

    bpy.data.images.remove(img)

    return {
        "image": str(path),
        "palette": colors,
        "count": len(colors),
    }


def map_design_elements(
    source_aircraft: str,
    target_aircraft: str,
    elements: list[dict],
) -> dict[str, Any]:
    """Map design elements from source to target aircraft UV layout.

    Args:
        source_aircraft: Source aircraft ID
        target_aircraft: Target aircraft ID
        elements: List of design elements to map

    Returns:
        Dictionary with mapping information
    """
    from .templates import SUPPORTED_AIRCRAFT

    if source_aircraft not in SUPPORTED_AIRCRAFT:
        return {"error": f"Unknown source aircraft: {source_aircraft}"}
    if target_aircraft not in SUPPORTED_AIRCRAFT:
        return {"error": f"Unknown target aircraft: {target_aircraft}"}

    source_info = SUPPORTED_AIRCRAFT[source_aircraft]
    target_info = SUPPORTED_AIRCRAFT[target_aircraft]

    mapped_elements = []

    for element in elements:
        element_type = element.get("type", "unknown")
        mapped = {
            "type": element_type,
            "source_position": element.get("position", {}),
        }

        # Simple proportional mapping for now
        # In production, this would use ML-based UV correspondence
        if "position" in element:
            pos = element["position"]
            # Map normalized positions
            mapped["target_position"] = {
                "y_normalized": pos.get("y_normalized", 0.5),
                "x_normalized": pos.get("x_normalized", 0.5),
            }

        mapped["mapping_method"] = DESIGN_ELEMENTS.get(element_type, {}).get(
            "transfer_method", "region_mapping"
        )
        mapped_elements.append(mapped)

    return {
        "source_aircraft": source_aircraft,
        "target_aircraft": target_aircraft,
        "source_texture_size": source_info.get("texture_size", [4096, 4096]),
        "target_texture_size": target_info.get("texture_size", [4096, 4096]),
        "mapped_elements": mapped_elements,
        "note": "Use transfer_livery with AI generation for full transfer",
    }


def transfer_livery(
    source_image_path: str,
    source_aircraft: str,
    target_aircraft: str,
    output_path: str,
    airline_name: str | None = None,
    use_ai_generation: bool = True,
) -> dict[str, Any]:
    """Transfer a livery design from one aircraft to another.

    This is the main AI-assisted transfer function. It:
    1. Analyzes the source livery
    2. Extracts design elements and colors
    3. Maps elements to target UV layout
    4. Generates new texture using AI (if enabled)

    Args:
        source_image_path: Path to source livery texture
        source_aircraft: Source aircraft ID
        target_aircraft: Target aircraft ID
        output_path: Output path for generated texture
        airline_name: Optional airline name for context
        use_ai_generation: Use AI to generate adapted texture

    Returns:
        Dictionary with transfer results
    """
    from .templates import SUPPORTED_AIRCRAFT

    # Validate inputs
    source_path = Path(source_image_path)
    if not source_path.exists():
        return {"error": f"Source image not found: {source_image_path}"}

    if source_aircraft not in SUPPORTED_AIRCRAFT:
        return {"error": f"Unknown source aircraft: {source_aircraft}"}
    if target_aircraft not in SUPPORTED_AIRCRAFT:
        return {"error": f"Unknown target aircraft: {target_aircraft}"}

    # Analyze source livery
    analysis = analyze_livery(source_image_path, source_aircraft)
    if "error" in analysis:
        return analysis

    # Map elements to target
    mapping = map_design_elements(
        source_aircraft,
        target_aircraft,
        analysis.get("detected_elements", []),
    )

    result = {
        "source_image": str(source_path),
        "source_aircraft": source_aircraft,
        "target_aircraft": target_aircraft,
        "output_path": output_path,
        "analysis": {
            "color_palette": analysis.get("color_palette", []),
            "detected_elements": analysis.get("detected_elements", []),
        },
        "mapping": mapping,
    }

    if airline_name:
        result["airline"] = airline_name

    if use_ai_generation:
        # Prepare prompt for AI generation
        target_info = SUPPORTED_AIRCRAFT[target_aircraft]
        target_size = target_info.get("texture_size", [4096, 4096])

        colors_desc = ", ".join(
            c["hex"] for c in analysis.get("color_palette", [])[:5]
        )

        ai_prompt = (
            f"Aircraft livery texture for {target_info['name']}. "
            f"Transfer design from {SUPPORTED_AIRCRAFT[source_aircraft]['name']}. "
            f"Color palette: {colors_desc}. "
        )

        if airline_name:
            ai_prompt += f"Airline: {airline_name}. "

        elements_desc = [e["type"] for e in analysis.get("detected_elements", [])]
        if elements_desc:
            ai_prompt += f"Design elements: {', '.join(elements_desc)}. "

        ai_prompt += "UV-mapped aircraft texture, professional airline livery."

        result["ai_generation"] = {
            "prompt": ai_prompt,
            "target_size": target_size,
            "status": "ready",
            "instructions": (
                "Use blender_livery_generate_texture with this prompt to generate "
                "the transferred livery using AI image generation."
            ),
        }

        # Store analysis data for generation
        result["transfer_data"] = {
            "source_base64": analysis.get("image_base64", ""),
            "target_size": target_size,
            "color_palette": analysis.get("color_palette", []),
            "elements": analysis.get("detected_elements", []),
        }
    else:
        result["manual_transfer"] = {
            "instructions": (
                "Manual transfer mode. Use the color palette and element mapping "
                "to recreate the livery on the target aircraft template."
            ),
        }

    return result


def generate_livery_texture(
    transfer_data: dict,
    output_path: str,
    api_provider: str = "stability",
) -> dict[str, Any]:
    """Generate a livery texture using AI image generation.

    This function interfaces with image generation APIs to create
    the transferred livery texture.

    Args:
        transfer_data: Data from transfer_livery result
        output_path: Output path for generated texture
        api_provider: AI provider (stability, openai, replicate)

    Returns:
        Dictionary with generation results
    """
    # Check for API keys
    api_keys = {
        "stability": os.environ.get("STABILITY_API_KEY"),
        "openai": os.environ.get("OPENAI_API_KEY"),
        "replicate": os.environ.get("REPLICATE_API_TOKEN"),
    }

    if api_provider not in api_keys:
        return {
            "error": f"Unknown API provider: {api_provider}",
            "available": list(api_keys.keys()),
        }

    api_key = api_keys[api_provider]
    if not api_key:
        return {
            "error": f"API key not set for {api_provider}",
            "required_env_var": {
                "stability": "STABILITY_API_KEY",
                "openai": "OPENAI_API_KEY",
                "replicate": "REPLICATE_API_TOKEN",
            }[api_provider],
        }

    # Extract generation parameters
    prompt = transfer_data.get("ai_generation", {}).get("prompt", "")
    target_size = transfer_data.get("ai_generation", {}).get("target_size", [4096, 4096])
    source_image = transfer_data.get("transfer_data", {}).get("source_base64", "")

    if not prompt:
        return {"error": "No generation prompt found in transfer_data"}

    result = {
        "api_provider": api_provider,
        "prompt": prompt,
        "target_size": target_size,
        "output_path": output_path,
    }

    # In production, this would call the actual API
    # For now, return instructions for manual integration
    result["status"] = "pending"
    result["instructions"] = (
        f"AI generation ready. Use the {api_provider} API with:\n"
        f"- Prompt: {prompt}\n"
        f"- Size: {target_size[0]}x{target_size[1]}\n"
        f"- Input image (for img2img): {len(source_image)} bytes base64\n"
        f"\nIntegrate with MCP image generation server or call API directly."
    )

    # Store for potential MCP integration
    result["mcp_integration"] = {
        "suggested_tool": "mcp__image_generation__generate",
        "parameters": {
            "prompt": prompt,
            "width": target_size[0],
            "height": target_size[1],
            "input_image_base64": source_image[:100] + "..." if source_image else None,
        },
    }

    return result
