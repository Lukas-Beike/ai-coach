"""Display-only nutrient totals derived from frozen consumption snapshots."""

from typing import Any

INTAKE_FIELDS = ("sugar_g", "salt_g")


def _snapshot_values(basis: dict[str, Any], key: str) -> list[float | None]:
    kind = basis.get("kind")
    if kind == "composite":
        return [
            value
            for component in basis.get("components", [])
            for value in _snapshot_values(
                {**component.get("nutrition_basis", {}), "amount": component["amount"]},
                key,
            )
        ] or [None]
    if kind == "database":
        ingredients = basis.get("ingredients")
        if ingredients is None:
            ingredients = [{**basis.get("food", {}), "amount": basis.get("amount")}]
        return [
            None
            if item.get("per_100", {}).get(key) is None
            else float(item["per_100"][key]) * float(item["amount"]) / 100
            for item in ingredients
        ] or [None]
    if kind == "local_product":
        product = basis.get("product", {})
        value = product.get(key)
        return [
            None
            if value is None
            else float(value) * float(basis["amount"]) / float(product["basis_amount"])
        ]
    return [None]


def add_intake_totals(summary: dict[str, Any]) -> None:
    """Keep unknowns distinct from zero and partial sums distinct from totals.

    Never consult today's product catalog: historical intake uses the source and
    quantity saved with each meal, including scaled template portions.
    """
    known_totals = {}
    for key in INTAKE_FIELDS:
        values = [
            value
            for entry in summary["entries"]
            for value in _snapshot_values(entry.get("nutrition_basis", {}), key)
        ]
        known = [value for value in values if value is not None]
        known_totals[key] = round(sum(known), 1) if known else None
        summary[f"total_{key}"] = (
            known_totals[key] if values and len(known) == len(values) else None
        )
    summary["known_intake_totals"] = known_totals
