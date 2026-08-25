"""What a brand-new workspace contains.

A real product with nothing in it, not a sample. A planner that arrives pre-filled with
invented projects makes the first real one harder to see, and every fake row is something a
person has to delete before they can start. The empty index says so in words instead.
"""

from dplanner.core.storage.provider import StorageProvider
from dplanner.domain.model import Product
from dplanner.domain.store import ProductStore


def create_product(storage: StorageProvider) -> None:
    """Write an empty product named after the folder it lives in."""
    name = storage.root.name.replace("-", " ").replace("_", " ").strip().title()
    ProductStore(storage).create(Product(name=name or "New Product"))
