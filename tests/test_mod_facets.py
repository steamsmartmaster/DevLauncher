# -*- coding: utf-8 -*-
"""Modrinth facets 构建（launcher_core.api_modrinth.build_facets）。

语义：每个子数组 = OR，子数组之间 = AND。
versions→versions 组；loaders/categories→categories: slug 各自独立组；
environments→client_side/server_side（实测 categories:client 恒 0，环境非 category）。
"""
import json

from launcher_core.api_modrinth import build_facets


def test_defaults_project_type_only():
    assert build_facets(project_type="mods") == [["project_type:mod"]]


def test_versions_group():
    facets = build_facets(project_type="mods", versions=["1.21.11", "1.21.8"])
    # 多选版本必须同组（组内 OR），拆成两组会变成 AND（永远搜不到）
    assert ["versions:1.21.11", "versions:1.21.8"] in facets
    assert ["project_type:mod"] in facets


def test_loaders_categories_are_category_groups():
    facets = build_facets(
        project_type="mods",
        loaders=["fabric", "neoforge"],
        categories=["adventure", "optimization"],
        environments=["client"],
    )
    assert ["categories:fabric", "categories:neoforge"] in facets
    assert ["categories:adventure", "categories:optimization"] in facets
    # 环境走 client_side（required+optional 组内 OR），不是 categories:client
    assert ["client_side:required", "client_side:optional"] in facets
    assert not any("categories:client" in g for g in facets), "环境不应是 categories:client"
    # 各组独立（AND 关系），不能并成一个大 OR
    loader_groups = [g for g in facets if g and g[0] == "categories:fabric"]
    assert len(loader_groups) == 1


def test_environments_both_ends_are_and_groups():
    facets = build_facets(project_type="mods", environments=["client", "server"])
    assert ["client_side:required", "client_side:optional"] in facets
    assert ["server_side:required", "server_side:optional"] in facets


def test_all_groups_together_and_ordered_after_project_type():
    facets = build_facets(
        project_type="mods",
        versions=["1.21.4"],
        loaders=["fabric"],
        categories=["magic"],
        environments=["server"],
    )
    assert facets[0] == ["project_type:mod"]
    assert len(facets) == 5
    json.dumps(facets)  # 必须可序列化


def test_empty_lists_ignored():
    facets = build_facets(project_type="mods", versions=[], loaders=[], categories=[], environments=[])
    assert facets == [["project_type:mod"]]


def test_project_types_mapping():
    # datapacks 的 project_type facet 不是 mod
    assert build_facets(project_type="datapacks") == [["project_type:datapack"]]
