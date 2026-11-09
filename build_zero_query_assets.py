import os
import argparse
import sqlite3
from collections import defaultdict

from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.RWGltf import RWGltf_CafWriter
from OCP.TDF import TDF_Label, TDF_Tool
from OCP.TDataStd import TDataStd_Name
from OCP.collections import Sequence_TDF_Label, IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString
from OCP.RWMesh import RWMesh_CoordinateSystemConverter
from OCP.Message import Message_ProgressRange
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound
from OCP.TopLoc import TopLoc_Location
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

def get_label_name(label):
    name_attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
        return name_attr.Get().ToExtString()
    return "Unnamed_Component"

def resolve(label):
    """Follow an assembly component reference to the part/assembly definition label."""
    ref = TDF_Label()
    if XCAFDoc_ShapeTool.GetReferredShape_s(label, ref):
        return ref
    return label

def label_key(label):
    entry = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, entry)
    return entry.ToCString()

def components_of(label):
    comps = Sequence_TDF_Label()
    if not XCAFDoc_ShapeTool.GetComponents_s(label, comps):
        return []
    return [comps.Value(i) for i in range(1, comps.Length() + 1)]

def bbox_limits(bbox):
    lo, hi = bbox.CornerMin(), bbox.CornerMax()
    return lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()

def calculate_bounding_box_metrics(shape):
    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    if bbox.IsVoid():
        return 0.0, (0.0, 0.0, 0.0)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox_limits(bbox)
    dx, dy, dz = round(xmax-xmin, 1), round(ymax-ymin, 1), round(zmax-zmin, 1)
    return (dx * dy * dz), tuple(sorted([dx, dy, dz]))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='factory_assembly.step')
    parser.add_argument('--glb', default='cad_model.glb')
    parser.add_argument('--sqlite', default='bom_data.sqlite')
    parser.add_argument('--keep-fasteners', action='store_true',
                        help='Keep small high-count parts in the GLB (they are still classified as Group 1 in the BOM)')
    parser.add_argument('--fastener-min-count', type=int, default=12, help='Min instances for a part to count as a fastener')
    parser.add_argument('--fastener-max-volume', type=float, default=8000.0, help='Max bounding-box volume (mm^3) of a fastener')
    parser.add_argument('--max-depth', type=int, default=0,
                        help='Hierarchy levels to keep in the GLB (root = level 1). Assemblies at this level are merged '
                             'into one node. 0 = keep the full hierarchy')
    args = parser.parse_args()

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(args.input) != IFSelect_RetDone: raise Exception("STEP Read Failed")
    if not reader.Transfer(doc): raise Exception("STEP Transfer Failed")

    shape_frequency = defaultdict(int)
    hash_to_shape_map = {}
    hash_to_name_map = {}

    def profile_hierarchy(label):
        label = resolve(label)
        comps = components_of(label)
        if comps:
            for c in comps: profile_hierarchy(c)
        else:
            shape = XCAFDoc_ShapeTool.GetShape_s(label)
            if not shape.IsNull():
                s_hash = label_key(label)
                shape_frequency[s_hash] += 1
                if s_hash not in hash_to_shape_map:
                    hash_to_shape_map[s_hash] = shape
                    hash_to_name_map[s_hash] = get_label_name(label)

    free_shapes = Sequence_TDF_Label()
    shape_tool.GetFreeShapes(free_shapes)
    for i in range(1, free_shapes.Length() + 1): profile_hierarchy(free_shapes.Value(i))

    geometric_bins = defaultdict(list)
    hardware_hashes = set()
    for s_hash, count in shape_frequency.items():
        _, sorted_dims = calculate_bounding_box_metrics(hash_to_shape_map[s_hash])
        geometric_bins[sorted_dims].append(s_hash)

    if os.path.exists(args.sqlite): os.remove(args.sqlite)
    conn = sqlite3.connect(args.sqlite)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE bom (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            classification TEXT,
            sample_name TEXT,
            occurrences INTEGER,
            volume FLOAT,
            dimensions TEXT,
            pipeline_action TEXT,
            cost REAL DEFAULT 0.0,
            op_lead_time INTEGER DEFAULT 0,
            notes TEXT DEFAULT ''
        );
    """)

    for dims, hashes in geometric_bins.items():
        total_occurrences = sum(shape_frequency[h] for h in hashes)
        sample_shape = hash_to_shape_map[hashes[0]]
        bbox = Bnd_Box()
        BRepBndLib.Add_s(sample_shape, bbox)
        xmin, ymin, zmin, xmax, ymax, zmax = bbox_limits(bbox)
        volume = (xmax-xmin)*(ymax-ymin)*(zmax-zmin)
        sample_name = hash_to_name_map[hashes[0]]
        
        if total_occurrences >= args.fastener_min_count and volume <= args.fastener_max_volume:
            if not args.keep_fasteners:
                for h in hashes: hardware_hashes.add(h)
            action, group = ("RETAINED" if args.keep_fasteners else "DELETED"), "Group 1: Small Fasteners (High Count)"
        elif volume <= 8000.0:
            action, group = "RETAINED", "Group 3: Unique Machine Geometry (Low Count)"
        else:
            action, group = "RETAINED", "Group 2: Modular Structures (High Count Preserved)"

        cursor.execute("""
            INSERT INTO bom (classification, sample_name, occurrences, volume, dimensions, pipeline_action)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (group, sample_name, total_occurrences, round(volume, 2), f"{dims[0]}x{dims[1]}x{dims[2]}", action))
    
    # Track model bounds for dynamic camera scaling
    overall_bbox = Bnd_Box()
    for i in range(1, free_shapes.Length() + 1):
        s = XCAFDoc_ShapeTool.GetShape_s(free_shapes.Value(i))
        if not s.IsNull(): BRepBndLib.Add_s(s, overall_bbox)

    xmin, ymin, zmin, xmax, ymax, zmax = bbox_limits(overall_bbox)
    cx, cy, cz = (xmin+xmax)/2, (ymin+ymax)/2, (zmin+zmax)/2
    max_dim = max(xmax-xmin, ymax-ymin, zmax-zmin)
    
    cursor.execute("CREATE TABLE viewer_metadata (cx REAL, cy REAL, cz REAL, max_dim REAL);")
    cursor.execute("INSERT INTO viewer_metadata VALUES (?, ?, ?, ?);", (cx, cy, cz, max_dim))
    
    conn.commit()
    conn.close()

    # Drop suppressed fasteners from every assembly definition (shared by all instances)
    visited = set()
    def remove_hardware(label):
        label = resolve(label)
        key = label_key(label)
        if key in visited: return
        visited.add(key)
        for comp in components_of(label):
            if label_key(resolve(comp)) in hardware_hashes:
                shape_tool.RemoveComponent(comp)
            else:
                remove_hardware(comp)

    for i in range(1, free_shapes.Length() + 1): remove_hardware(free_shapes.Value(i))
    # Merge assemblies at the depth limit into a single node
    if args.max_depth > 0:
        merged = {}
        def leaf_shapes(label, loc, out):
            label = resolve(label)
            comps = components_of(label)
            if not comps:
                shape = XCAFDoc_ShapeTool.GetShape_s(label)
                if not shape.IsNull(): out.append(shape.Moved(loc))
                return
            for c in comps:
                child_loc = XCAFDoc_ShapeTool.GetLocation_s(c)
                leaf_shapes(c, loc.Multiplied(child_loc), out)

        def flatten(parent, depth):
            parent = resolve(parent)
            for comp in components_of(parent):
                ref = resolve(comp)
                if not components_of(ref): continue
                if depth + 1 < args.max_depth:
                    flatten(comp, depth + 1)
                    continue
                key = label_key(ref)
                if key not in merged:
                    builder = BRep_Builder(); compound = TopoDS_Compound(); builder.MakeCompound(compound)
                    shapes = []
                    leaf_shapes(ref, TopLoc_Location(), shapes)
                    for sh in shapes: builder.Add(compound, sh)
                    new_part = shape_tool.AddShape(compound, False, False)
                    TDataStd_Name.Set_s(new_part, TCollection_ExtendedString(get_label_name(ref)))
                    merged[key] = new_part
                location = XCAFDoc_ShapeTool.GetLocation_s(comp)
                shape_tool.RemoveComponent(comp)
                shape_tool.AddComponent(parent, merged[key], location)

        for i in range(1, free_shapes.Length() + 1): flatten(free_shapes.Value(i), 1)

    # Name every component node after the part/assembly it references so the GLB hierarchy is readable
    named = set()
    def name_components(label):
        label = resolve(label)
        key = label_key(label)
        if key in named: return
        named.add(key)
        for comp in components_of(label):
            ref = resolve(comp)
            TDataStd_Name.Set_s(comp, TCollection_ExtendedString(get_label_name(ref)))
            name_components(comp)

    for i in range(1, free_shapes.Length() + 1): name_components(free_shapes.Value(i))
    shape_tool.UpdateAssemblies()

    for i in range(1, free_shapes.Length() + 1):
        shape = XCAFDoc_ShapeTool.GetShape_s(free_shapes.Value(i))
        if not shape.IsNull(): BRepMesh_IncrementalMesh(shape, 0.5, False, 0.5, True)

    writer = RWGltf_CafWriter(TCollection_AsciiString(args.glb), True)
    # Keep millimetres (the viewer's units) instead of glTF's metres
    converter = RWMesh_CoordinateSystemConverter()
    converter.SetInputLengthUnit(0.001)
    converter.SetOutputLengthUnit(0.001)
    writer.SetCoordinateSystemConverter(converter)
    file_info = IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString()
    if not writer.Perform(doc, file_info, Message_ProgressRange()):
        raise Exception("GLB export failed")
    print("Zero-Query Assets Built Successfully!")

if __name__ == "__main__":
    main()
