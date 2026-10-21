"""Frozen entry point for the optional local CAD runtime component."""

import sys
from types import ModuleType

# OCP's IVtk compatibility packages import ``vtk`` only to register the legacy
# all-in-one namespace.  The trusted worker uses CadQuery's explicit
# ``vtkmodules`` imports instead; loading the legacy namespace eagerly opens
# every VTK plug-in and makes a frozen worker take minutes to start.  Supplying
# the harmless compatibility module keeps the native IVtk bindings available
# without importing VTK's GUI, test and scientific-visualisation surface.
sys.modules.setdefault("vtk", ModuleType("vtk"))

from app.cad_worker import main


if __name__ == "__main__":
    main()
