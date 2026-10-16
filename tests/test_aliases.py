import pytest

from lore.aliases import AliasError, Aliases


def test_add_resolve_and_survive_reload(store, home):
    al = Aliases()
    item = store.get("mini:1.1#1")
    a, replaced = al.add_ref("undo", item, store=store)
    assert not replaced and a.name == "undo"
    again = Aliases()
    res = again.resolve(again.get("@undo"), store)
    assert res.item.id == "mini:1.1#1" and not res.moved


def test_replace_reports_it(store, home):
    al = Aliases()
    al.add_ref("x", store.get("mini:1.1"), store=store)
    _a, replaced = al.add_ref("x", store.get("mini:1.2"), store=store)
    assert replaced and al.get("x").target == "mini:1.2"


def test_names_are_validated(store, home):
    al = Aliases()
    for bad in ("", "has space", "-lead", "a" * 40, "mini"):
        with pytest.raises(AliasError):
            al.add_ref(bad, store.get("mini:1.1"), store=store)


def test_text_alias(home):
    al = Aliases()
    al.add_text("deploy", "kubectl rollout undo deploy/web")
    assert Aliases().get("deploy").text.startswith("kubectl")
    with pytest.raises(AliasError):
        al.add_text("empty", "  ")


def test_rename_remove_and_usage_order(store, home):
    al = Aliases()
    al.add_ref("a", store.get("mini:1.1"), store=store)
    al.add_ref("b", store.get("mini:1.2"), store=store)
    al.touch("b")
    assert [x.name for x in al.ordered()] == ["b", "a"]
    al.rename("a", "c", store)
    assert al.get("a") is None and al.get("c")
    assert al.remove("c") and not al.remove("c")


def test_alias_is_found_again_after_the_numbering_moves(store, home):
    al = Aliases()
    al.add_ref("rv", store.get("mini:1.2"), store=store)
    al.items["rv"].target = "mini:9.9"  # as if the course had been renumbered
    res = al.resolve(al.get("rv"), store)
    assert res.item.id == "mini:1.2" and res.moved


def test_missing_target(store, home):
    al = Aliases()
    al.add_ref("gone", store.get("mini:1.2"), store=store)
    al.items["gone"].target, al.items["gone"].slug = "mini:9.9", "no-such-slug"
    assert al.resolve(al.get("gone"), store).missing
