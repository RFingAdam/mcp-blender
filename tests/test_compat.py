"""Blender-free tests for the compatibility layer.

compat.py imports only ``bpy``, so a stub stands in for it. Each stub is shaped
like one API: the attribute is present, or it is missing. No test sets a version
number, because compat.py never reads one.
"""

import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

COMPAT = Path(__file__).resolve().parent.parent / "addon" / "blender_mcp_addon" / "compat.py"


def ns(**kw):
    return types.SimpleNamespace(**kw)


class Coll(list):
    """A collection that records new() calls. Empty ones are falsy, like Blender's."""

    def new(self, *args, **kwargs):
        item = ns(name=args[0] if args else "", args=args, kwargs=kwargs)
        self.append(item)
        return item


def enum_prop(*identifiers):
    return ns(enum_items=[ns(identifier=i) for i in identifiers])


def rna_type(**props):
    return ns(bl_rna=ns(properties=props))


@pytest.fixture
def bpy(monkeypatch):
    stub = types.ModuleType("bpy")
    stub.app = ns()
    stub.types = ns(
        RenderSettings=rna_type(engine=enum_prop("BLENDER_WORKBENCH")),
        BooleanModifier=rna_type(solver=enum_prop("EXACT")),
        Scene=rna_type(),
    )
    stub.data = ns()
    stub.ops = ns(mesh=ns())
    monkeypatch.setitem(sys.modules, "bpy", stub)
    return stub


@pytest.fixture
def compat(bpy):
    spec = importlib.util.spec_from_file_location("_compat_under_test", COMPAT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- engine and solver names ------------------------------------------------------


def test_eevee_name_prefers_next_when_offered(bpy, compat):
    bpy.types.RenderSettings = rna_type(engine=enum_prop("BLENDER_EEVEE_NEXT", "CYCLES"))
    assert compat.get_eevee_engine_name() == "BLENDER_EEVEE_NEXT"


def test_eevee_name_falls_back_to_plain_name(bpy, compat):
    bpy.types.RenderSettings = rna_type(engine=enum_prop("BLENDER_EEVEE", "CYCLES"))
    assert compat.get_eevee_engine_name() == "BLENDER_EEVEE"


def test_eevee_name_with_no_enum_to_read(bpy, compat):
    bpy.types.RenderSettings = rna_type()
    assert compat.get_eevee_engine_name() == "BLENDER_EEVEE"


@pytest.mark.parametrize(
    "offered,expected",
    [
        (("BLENDER_EEVEE_NEXT",), "BLENDER_EEVEE_NEXT"),
        (("BLENDER_EEVEE",), "BLENDER_EEVEE"),
    ],
)
@pytest.mark.parametrize("spelling", ["EEVEE", "blender_eevee", "BLENDER_EEVEE_NEXT"])
def test_every_eevee_spelling_maps_to_the_offered_engine(bpy, compat, offered, expected, spelling):
    bpy.types.RenderSettings = rna_type(engine=enum_prop(*offered, "CYCLES"))
    assert compat.resolve_render_engine(spelling) == expected


def test_other_engines_pass_through(bpy, compat):
    assert compat.resolve_render_engine("CYCLES") == "CYCLES"


@pytest.mark.parametrize(
    "offered,asked,expected",
    [
        (("FAST", "EXACT"), "FAST", "FAST"),
        (("FLOAT", "EXACT"), "FAST", "FLOAT"),
        (("FAST", "EXACT"), "FLOAT", "FAST"),
        (("FLOAT", "EXACT"), "EXACT", "EXACT"),
        (("FLOAT", "EXACT"), "MANIFOLD", "MANIFOLD"),
    ],
)
def test_boolean_solver(bpy, compat, offered, asked, expected):
    bpy.types.BooleanModifier = rna_type(solver=enum_prop(*offered))
    assert compat.boolean_solver(asked) == expected


# ---- edge loops -------------------------------------------------------------------


def test_edge_loops_use_the_single_operator_when_present(bpy, compat):
    calls = []
    bpy.ops.mesh = ns(loop_multi_select=lambda **kw: calls.append(("single", kw)))
    compat.select_edge_loops(True)
    assert calls == [("single", {"ring": True})]


@pytest.mark.parametrize("ring,name", [(False, "loop"), (True, "ring")])
def test_edge_loops_use_the_split_operators_otherwise(bpy, compat, ring, name):
    calls = []
    bpy.ops.mesh = ns(
        select_edge_loop_multi=lambda: calls.append("loop"),
        select_edge_ring_multi=lambda: calls.append("ring"),
    )
    compat.select_edge_loops(ring)
    assert calls == [name]


# ---- action curves ----------------------------------------------------------------


def test_fcurves_of_a_legacy_action(compat):
    action = ns(layers=[], fcurves=["a", "b"])
    assert compat.get_fcurves(action) == ["a", "b"]


def test_fcurves_of_an_action_with_no_layers_attribute(compat):
    assert compat.get_fcurves(ns(fcurves=["a"])) == ["a"]


def test_fcurves_of_a_layered_action_come_from_channelbags(compat):
    bag1 = ns(slot_handle=1, fcurves=["x"])
    bag2 = ns(slot_handle=2, fcurves=["y", "z"])
    strip = ns(channelbags=[bag1, bag2])
    action = ns(layers=[ns(strips=[strip])])
    assert compat.get_fcurves(action) == ["x", "y", "z"]
    assert compat.get_fcurves(action, ns(handle=2)) == ["y", "z"]


def test_layered_action_never_touches_a_slot_layers_attribute(compat):
    # The old code read slot.layers, which slots do not have.
    action = ns(layers=[ns(strips=[ns(channelbags=[ns(slot_handle=1, fcurves=["x"])])])])
    slot = ns(handle=1)
    assert not hasattr(slot, "layers")
    assert compat.get_fcurves(action, slot) == ["x"]


def test_object_keyframes_read_only_the_assigned_slot(compat):
    def curve(path, frames):
        return ns(
            data_path=path,
            array_index=0,
            keyframe_points=[ns(co=(f, f * 2.0)) for f in frames],
        )

    bags = [
        ns(slot_handle=1, fcurves=[curve("location", [1, 5])]),
        ns(slot_handle=2, fcurves=[curve("scale", [3])]),
    ]
    action = ns(layers=[ns(strips=[ns(channelbags=bags)])])
    obj = ns(animation_data=ns(action=action, action_slot=ns(handle=2)))
    assert list(compat.get_object_keyframes(obj)) == ["scale"]


def test_no_animation_gives_no_keyframes(compat):
    assert compat.get_object_keyframes(ns(animation_data=None)) == {}


def test_list_actions_reports_slots_only_where_they_exist(bpy, compat):
    layered = ns(
        name="L",
        users=1,
        frame_range=(1, 2),
        slots=[1, 2],
        layers=[ns(strips=[ns(channelbags=[ns(slot_handle=1, fcurves=["c"])])])],
    )
    legacy = ns(name="G", users=1, frame_range=(1, 2), fcurves=["a", "b"])
    bpy.data.actions = [layered, legacy]
    by_name = {a["name"]: a for a in compat.list_actions()}
    assert by_name["L"]["slots"] == 2 and by_name["L"]["fcurves"] == 1
    assert "slots" not in by_name["G"] and by_name["G"]["fcurves"] == 2


# ---- Geometry Nodes modifier inputs -----------------------------------------------


def test_modifier_inputs_via_the_properties_api(compat):
    socket = ns(value=1.5)
    modifier = ns(properties=ns(inputs=ns(Socket_2=socket)))
    assert compat.get_modifier_input(modifier, "Socket_2") == 1.5
    compat.set_modifier_input(modifier, "Socket_2", 4.0)
    assert socket.value == 4.0


def test_modifier_input_without_a_value_or_socket_reads_as_none(compat):
    modifier = ns(properties=ns(inputs=ns(Socket_0=ns())))
    assert compat.get_modifier_input(modifier, "Socket_0") is None
    assert compat.get_modifier_input(modifier, "Socket_9") is None
    with pytest.raises(KeyError):
        compat.set_modifier_input(modifier, "Socket_9", 1)


class IdPropModifier(dict):
    """A modifier whose inputs are custom properties, with no ``properties`` attribute."""


def test_modifier_inputs_via_custom_properties(compat):
    modifier = IdPropModifier(Socket_2=2.0)
    assert compat.get_modifier_input(modifier, "Socket_2") == 2.0
    assert compat.get_modifier_input(modifier, "Socket_3") is None
    compat.set_modifier_input(modifier, "Socket_3", 7)
    assert modifier["Socket_3"] == 7


# ---- annotations ------------------------------------------------------------------


def test_annotation_data_lives_on_scene_annotation_when_offered(bpy, compat):
    bpy.types.Scene = rna_type(annotation=object())
    bpy.data.annotations = Coll()
    bpy.data.grease_pencils = Coll()
    scene = ns(annotation=None, grease_pencil=None)
    assert compat.get_annotation_data(scene) is None
    data = compat.get_annotation_data(scene, create=True)
    assert scene.annotation is data and len(bpy.data.annotations) == 1
    assert len(bpy.data.grease_pencils) == 0
    assert compat.get_annotation_data(scene) is data


def test_annotation_data_lives_on_scene_grease_pencil_otherwise(bpy, compat):
    bpy.types.Scene = rna_type(grease_pencil=object())
    bpy.data.grease_pencils = Coll()
    scene = ns(grease_pencil=None)
    data = compat.get_annotation_data(scene, create=True)
    assert scene.grease_pencil is data and len(bpy.data.grease_pencils) == 1


def frame_type(strokes_srna):
    return ns(bl_rna=ns(properties={"strokes": ns(srna=strokes_srna)}))


def test_annotation_strokes_are_creatable_when_strokes_has_new(bpy, compat):
    bpy.types.AnnotationFrame = frame_type(ns(functions={"new": 1, "remove": 2}))
    assert compat.can_add_annotation_strokes() is True


def test_annotation_strokes_are_not_creatable_without_new(bpy, compat):
    bpy.types.GPencilFrame = frame_type(None)
    assert compat.can_add_annotation_strokes() is False


def test_annotation_strokes_are_not_creatable_with_no_frame_type(bpy, compat):
    assert compat.can_add_annotation_strokes() is False


def test_annotation_stroke_skips_attributes_the_stroke_lacks(compat):
    new_stroke = ns(display_mode=None, points=_Points())
    frame = ns(strokes=ns(new=lambda: new_stroke))
    compat.add_annotation_stroke(frame, [(0, 0, 0), (1, 2, 3)], 4)
    assert new_stroke.display_mode == "3DSPACE"
    assert not hasattr(new_stroke, "line_width")
    assert [p.co for p in new_stroke.points.items] == [(0, 0, 0), (1, 2, 3)]
    assert not hasattr(new_stroke.points.items[0], "pressure")


def test_annotation_stroke_sets_width_and_pressure_where_offered(compat):
    new_stroke = ns(display_mode=None, line_width=0, points=_Points(with_pressure=True))
    frame = ns(strokes=ns(new=lambda: new_stroke))
    compat.add_annotation_stroke(frame, [(0, 0, 0), (1, 1, 1)], 4, strength=0.5)
    assert new_stroke.line_width == 4
    assert new_stroke.points.items[1].pressure == 1.0
    assert new_stroke.points.items[1].strength == 0.5


class _Points:
    def __init__(self, with_pressure=False):
        self.items = []
        self.with_pressure = with_pressure

    def add(self, n):
        for _ in range(n):
            point = ns(co=None)
            if self.with_pressure:
                point.pressure = 0.0
                point.strength = 0.0
            self.items.append(point)

    def __getitem__(self, i):
        return self.items[i]


# ---- grease pencil objects --------------------------------------------------------


def test_grease_pencil_data_prefers_the_v3_collection_even_when_empty(bpy, compat):
    bpy.data.grease_pencils_v3 = Coll()
    bpy.data.grease_pencils = Coll()
    compat.new_grease_pencil("G")
    assert len(bpy.data.grease_pencils_v3) == 1 and len(bpy.data.grease_pencils) == 0


def test_grease_pencil_data_uses_the_plain_collection_without_v3(bpy, compat):
    bpy.data.grease_pencils = Coll()
    compat.new_grease_pencil("G")
    assert len(bpy.data.grease_pencils) == 1


def test_layer_name_reads_info_or_name(compat):
    assert compat.layer_name(ns(info="Old")) == "Old"
    assert compat.layer_name(ns(name="New")) == "New"


class _Drawing:
    def __init__(self):
        self.strokes = []

    def add_strokes(self, sizes):
        for size in sizes:
            self.strokes.append(
                ns(
                    points=[
                        ns(position=None, radius=0, opacity=0, vertex_color=None)
                        for _ in range(size)
                    ]
                )
            )


def _layers(frame_for_layer):
    class Layers:
        def new(self, name):
            return ns(name=name, frames=ns(new=lambda n: frame_for_layer))

    return Layers()


def test_v3_strokes_are_drawn_through_the_drawing(compat):
    drawing = _Drawing()
    gpd = ns(layers=_layers(ns(drawing=drawing)))
    strokes = [([(0, 0, 0), (1, 0, 0)], 10), ([(0, 1, 0), (0, 2, 0), (0, 3, 0)], 20)]
    layer = compat.add_grease_pencil_strokes(gpd, strokes, (1, 0, 0, 0.5), 1)
    assert layer.name == "Layer"
    assert [len(s.points) for s in drawing.strokes] == [2, 3]
    assert drawing.strokes[1].points[2].position == (0, 3, 0)
    assert drawing.strokes[1].points[0].radius == pytest.approx(0.01)
    assert drawing.strokes[0].points[0].opacity == 0.5


def test_legacy_strokes_are_drawn_on_the_frame(compat):
    made = []

    def new_stroke():
        stroke = ns(display_mode=None, line_width=0, points=_Points(with_pressure=True))
        made.append(stroke)
        return stroke

    frame = ns(strokes=ns(new=new_stroke))
    layers = _layers(frame)
    gpd = ns(layers=layers)
    layer = compat.add_grease_pencil_strokes(gpd, [([(0, 0, 0), (1, 1, 1)], 6)], (0, 1, 0, 1), 3)
    assert len(made) == 1 and made[0].line_width == 6
    assert layer.name == "Layer"


# ---- compositor -------------------------------------------------------------------


def test_compositor_tree_is_the_scene_group_when_offered(bpy, compat):
    bpy.types.Scene = rna_type(compositing_node_group=object())
    bpy.data.node_groups = Coll()
    scene = ns(compositing_node_group=None)
    tree = compat.get_compositor_tree(scene)
    assert scene.compositing_node_group is tree
    assert tree.args == ("Compositor", "CompositorNodeTree")
    assert compat.get_compositor_tree(scene) is tree


def test_compositor_tree_is_node_tree_behind_use_nodes_otherwise(bpy, compat):
    bpy.types.Scene = rna_type(node_tree=object())
    scene = ns(use_nodes=False, node_tree="tree")
    assert compat.get_compositor_tree(scene) == "tree"
    assert scene.use_nodes is True


def _tree(sockets=()):
    made = []
    tree = ns(
        nodes=ns(new=lambda idname: made.append(idname) or ns(bl_idname=idname)),
        interface=ns(
            items_tree=list(sockets),
            new_socket=lambda name, **kw: tree.interface.items_tree.append(
                ns(item_type="SOCKET", in_out=kw["in_out"])
            ),
        ),
    )
    return tree, made


def test_output_node_is_composite_without_a_compositing_group(bpy, compat):
    tree, made = _tree()
    assert compat.new_compositor_output(tree).bl_idname == "CompositorNodeComposite"
    assert tree.interface.items_tree == []


def test_output_node_is_the_group_output_with_a_compositing_group(bpy, compat):
    bpy.types.Scene = rna_type(compositing_node_group=object())
    tree, made = _tree()
    assert compat.new_compositor_output(tree).bl_idname == "NodeGroupOutput"
    compat.new_compositor_output(tree)
    assert len(tree.interface.items_tree) == 1


# ---- misc -------------------------------------------------------------------------


def test_legacy_auto_smooth_is_detected_by_attribute(compat):
    assert compat.has_legacy_auto_smooth(ns(use_auto_smooth=False)) is True
    assert compat.has_legacy_auto_smooth(ns()) is False


def test_version_info_reports_features_from_detection(bpy, compat):
    bpy.app = ns(version=(), version_string="stub")
    bpy.types.Action = rna_type(layers=object())
    bpy.types.NodesModifier = rna_type(properties=object())
    bpy.types.Scene = rna_type()
    info = compat.get_version_info()
    assert info["features"] == {
        "layered_actions": True,
        "annotation_datablock": False,
        "compositing_node_group": False,
        "modifier_properties_api": True,
    }


def test_addon_never_compares_or_indexes_the_version():
    # Reporting the version string is fine; comparing, indexing or unpacking it is not.
    addon = COMPAT.parent
    bad = re.compile(
        r"(app\.version(_string)?\s*(\[|[<>=!]=?|\bin\b))"
        r"|(\bBLENDER_VERSION\b)|(\bIS_\d_\d_OR_LATER\b)"
        r"|(version_info\s*[<>=!]=?)|(\bversion\s*[<>]=?\s*\()"
    )
    hits = []
    for path in addon.rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if bad.search(line):
                hits.append(f"{path.relative_to(addon)}:{n}: {line.strip()}")
    assert not hits, hits
