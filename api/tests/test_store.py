from app.knowledge.store import store


def test_product_requirement_ranks_first_for_prototype_cost() -> None:
    results = store.search("Prototype B 成本")

    assert results
    assert results[0].id.startswith("product-requirement-v3")


def test_service_layer_adr_is_retrieved() -> None:
    results = store.search("直接連資料庫")

    assert any(result.id.startswith("adr-004") for result in results)
