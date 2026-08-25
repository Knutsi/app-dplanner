"""The product: a catalogue of projects, each a graph of steps.

**Product** is the system level — one codebase, the repository it lives in, and the projects
planned against it. A window holds one product.

**Project** is a unit of work. **Step** is a node in that project's graph, and edges between
steps are typed: ``requires`` orders the graph and refuses cycles, ``relates`` is a plain
link. An edge lives on the step that waits, so a step is self-contained and the direction
cannot be read the wrong way round.

**Aspects are what the graph does not know.** An estimate, a ticket, a description: none of
them are fields on :class:`Step`. Each is a module's entry in ``module_data`` (JSON) or
``module_text`` (prose), namespaced by module id and versioned by the module that writes it,
so features arrive without the graph learning anything about them.
"""

from dplanner.domain.model import NodeId, Product, Project, ProjectId, Step, StepId
from dplanner.domain.store import ProductStore

__all__ = ["NodeId", "Product", "ProductStore", "Project", "ProjectId", "Step", "StepId"]
