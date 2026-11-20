"""Semantic read witnesses (kit fixture matrix IDs in test names): reads follow attributions, not display parents."""

from django.urls import reverse

from tests.utils.AppTestCase import AppTestCase
from tests.utils.song_graph import install_song_graph

SONGS = reverse("song-list")


class TestSemanticReadsCutover(AppTestCase):
    def titles(self, genre, **params):
        response = self.api_client.get(SONGS, {"genre": str(genre.pk), "page_size": 100, **params})
        assert response.status_code == 200, response.json()
        return {row["title"] for row in response.json()["results"]}

    def dub_graph(self, reverse=False):
        factory = self.model_fixture_factory
        dub = factory.create_genre("Dub")
        regions = {code: factory.create_genre(f"{code} dub") for code in ("JM", "FR", "GB")}
        songs = {code: factory.create_song(f"{code} song", dub) for code in ("JM", "FR", "GB")}
        songs["DUB"] = factory.create_song("Dub song", dub)
        install_song_graph(
            {dub: [songs["DUB"]], **{regions[code]: [songs[code]] for code in regions}},
            relations=[(region, dub, "expression_style") for region in reversed(regions.values())]
            if reverse
            else [(region, dub, "expression_style") for region in regions.values()],
            node_overrides={region: {"kind": "expression"} for region in regions.values()},
        )
        return dub, regions

    def test_m01_canonical_dub_reaches_expressions_each_region_only_its_own(self):
        dub, regions = self.dub_graph()
        everything = {"Dub song", "JM song", "FR song", "GB song"}
        # Kit contract: canonical scope covers the expression populations, regional scope keeps the style itself.
        for scope in ("all", "canonical", "regional"):
            assert self.titles(dub, subgenres=scope) == everything
        assert self.titles(dub, coverage="genre_only") == {"Dub song"}
        for code, region in regions.items():
            assert self.titles(region) == {f"{code} song"}

    def test_m04_roots_reggae_anchoring_is_descriptive_and_does_not_double_count(self):
        factory = self.model_fixture_factory
        roots = factory.create_genre("Roots reggae")
        jamaica = factory.create_genre("Jamaica")
        france = factory.create_genre("France")
        jm_roots = factory.create_genre("Jamaican roots")
        fr_roots = factory.create_genre("French roots")
        jm_song = factory.create_song("JM roots", roots)
        fr_song = factory.create_song("FR roots", roots)
        overview = {"kind": "overview", "canonicalState": None}
        install_song_graph(
            {roots: [], jamaica: [], france: [], jm_roots: [jm_song], fr_roots: [fr_song]},
            relations=[
                (jm_roots, roots, "expression_style"),
                (fr_roots, roots, "expression_style"),
                (jm_roots, jamaica, "regional_membership"),
                (fr_roots, france, "regional_membership"),
                (roots, jamaica, "anchoring"),
            ],
            node_overrides={
                jamaica: overview,
                france: overview,
                jm_roots: {"kind": "expression"},
                fr_roots: {"kind": "expression"},
            },
        )
        assert self.titles(roots) == {"JM roots", "FR roots"}
        assert self.titles(jamaica) == {"JM roots"}
        assert self.titles(france) == {"FR roots"}

    def test_e07_regional_node_rejects_canonical_and_regional_scopes(self):
        _, regions = self.dub_graph()
        for scope in ("canonical", "regional"):
            response = self.api_client.get(SONGS, {"genre": str(regions["JM"].pk), "subgenres": scope})
            assert response.status_code == 400

    def test_e07_coverage_only_selects_direct_songs(self):
        dub, _ = self.dub_graph()
        assert self.titles(dub, coverage="genre_only") == {"Dub song"}

    def test_e11_expression_of_before_entry_style_is_absent_from_canonical(self):
        factory = self.model_fixture_factory
        rock = factory.create_genre("Rock")
        style = factory.create_genre("Celtic style")
        breton = factory.create_genre("Breton rock")
        songs = {name: factory.create_song(f"{name} song", rock) for name in ("Rock", "Style", "Breton")}
        install_song_graph(
            {rock: [songs["Rock"]], style: [songs["Style"]], breton: [songs["Breton"]]},
            relations=[(breton, style, "expression_style")],
            node_overrides={style: {"canonicalState": "before_entry"}, breton: {"kind": "expression"}},
        )
        assert self.titles(style) == {"Style song", "Breton song"}
        assert self.titles(rock, subgenres="canonical") == {"Rock song"}

    def test_e12_after_exit_fusion_is_reached_by_regional_and_all_not_canonical(self):
        factory = self.model_fixture_factory
        reggae = factory.create_genre("Reggae")
        fusion = factory.create_genre("French reggae fusion")
        songs = {name: factory.create_song(f"{name} song", reggae) for name in ("Reggae", "Fusion")}
        install_song_graph(
            {reggae: [songs["Reggae"]], fusion: [songs["Fusion"]]},
            classifications=[(fusion, reggae)],
            node_overrides={fusion: {"canonicalState": "after_exit"}},
            boundaries=[(fusion, "exit")],
        )
        both = {"Reggae song", "Fusion song"}
        assert self.titles(reggae, subgenres="canonical") == {"Reggae song"}
        assert self.titles(reggae, subgenres="regional") == both
        assert self.titles(reggae, subgenres="all") == both

    def test_e13_parentless_regional_root_is_selected_with_its_expression(self):
        factory = self.model_fixture_factory
        dub = factory.create_genre("Dub")
        jm_dub = factory.create_genre("JM dub")
        root = factory.create_genre("Kingston scene")
        songs = {name: factory.create_song(f"{name} song", dub) for name in ("Expression", "Root")}
        install_song_graph(
            {dub: [], jm_dub: [songs["Expression"]], root: [songs["Root"]]},
            relations=[(jm_dub, dub, "expression_style"), (root, jm_dub, "regional_membership")],
            node_overrides={jm_dub: {"kind": "expression"}, root: {"canonicalState": "before_entry"}},
        )
        assert self.titles(jm_dub) == {"Expression song", "Root song"}
        assert self.titles(root) == {"Root song"}

    def assert_dub_selections(self, dub, regions):
        assert self.titles(dub, subgenres="canonical") == {"Dub song", "JM song", "FR song", "GB song"}
        assert {code: self.titles(region) for code, region in regions.items()} == {
            code: {f"{code} song"} for code in regions
        }

    def test_e05_selections_are_the_same_with_relations_in_either_order(self):
        self.assert_dub_selections(*self.dub_graph())

    def test_e05_selections_are_the_same_with_relations_reversed(self):
        self.assert_dub_selections(*self.dub_graph(reverse=True))
