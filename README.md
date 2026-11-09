# STEP-BOM: Value Engineering 3D Workbench

Turns a STEP assembly into a GLB model plus a SQLite BOM, then views both in an offline browser workbench
(orbit, click-select, hierarchy list with depth slider, measuring with snapping, heatmap, ERP cost import, PDF report).

## Setup (Windows, Python 3.14)

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install cadquery-ocp trimesh
```

Offline: install from a wheelhouse with `pip install --no-index --find-links <wheelhouse> cadquery-ocp trimesh`.

## Run

Put your assembly in this folder as `factory_assembly.STEP`, then:

```powershell
.\run_pipeline.ps1                      # build cad_model.glb + bom_data.sqlite, serve, open browser
.\run_pipeline.ps1 -KeepFasteners       # keep small high-count parts
.\run_pipeline.ps1 -MaxDepth 2          # merge assemblies below hierarchy level 2
.\run_viewer.ps1                        # view existing glb + sqlite without rebuilding
```

The viewer's JavaScript libraries are vendored in `lib/`, so it works without internet. It must be served over
HTTP (the scripts do this with `python -m http.server`), not opened as a `file://` page.

STEP files and generated `cad_model.glb` / `bom_data.sqlite` are not tracked (see `.gitignore`).
