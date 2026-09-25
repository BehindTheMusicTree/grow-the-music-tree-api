from rest_framework import status
from the_music_tree_genre_kit.serializer.model.criteria.input.tree_import.Fields import Fields

from grow.model.criteria.children.genre.Genre import Genre
from tests.integration.criteria.GenreTestCase import GenreTestCase


class TestStructure(GenreTestCase):
    """`parent` is a self-FK declared on `Criteria`, so it always resolves to a plain
    `Criteria` instance -- never the `Genre` MTI subtype -- hence comparing by `pk`
    below rather than object equality."""

    def _mainstream_pop_root(self) -> dict:
        return {Fields.ID: "Q101", Fields.NAME_PUBLIC: "Mainstream Pop", Fields.CHILDREN: []}

    def test_single_root_then_ok(self):
        data = [{Fields.ID: "Q102", Fields.NAME_PUBLIC: "Rock", Fields.CHILDREN: []}, self._mainstream_pop_root()]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: data}
        )
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.count() == 2
        rock = genres.get(name="Rock")
        assert rock is not None
        assert rock.name == "Rock"
        assert rock.parent is None

    def test_multiple_roots_then_ok(self):
        data = [
            {Fields.ID: "Q103", Fields.NAME_PUBLIC: "Rock", Fields.CHILDREN: []},
            {Fields.ID: "Q104", Fields.NAME_PUBLIC: "Jazz", Fields.CHILDREN: []},
            self._mainstream_pop_root(),
        ]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: data}
        )
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.count() == 3
        rock = genres.get(name="Rock")
        jazz = genres.get(name="Jazz")
        assert rock is not None
        assert jazz is not None
        assert rock.parent is None
        assert jazz.parent is None

    def test_nested_structure_then_ok(self):
        data = [
            {
                Fields.ID: "Q116",
                Fields.NAME_PUBLIC: "Rock",
                Fields.CHILDREN: [
                    {
                        Fields.ID: "Q117",
                        Fields.NAME_PUBLIC: "Metal",
                        Fields.CHILDREN: [{Fields.ID: "Q105", Fields.NAME_PUBLIC: "Heavy Metal", Fields.CHILDREN: []}],
                    }
                ],
            },
            self._mainstream_pop_root(),
        ]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: data}
        )
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.count() == 4
        rock = genres.get(name="Rock")
        metal = genres.get(name="Metal")
        heavy_metal = genres.get(name="Heavy Metal")
        assert rock is not None
        assert metal is not None
        assert heavy_metal is not None
        assert rock.parent is None
        assert metal.parent.pk == rock.pk
        assert heavy_metal.parent.pk == metal.pk

    def test_deep_nesting_then_ok(self):
        data = [
            {
                Fields.ID: "Q118",
                Fields.NAME_PUBLIC: "Rock",
                Fields.CHILDREN: [
                    {
                        Fields.ID: "Q119",
                        Fields.NAME_PUBLIC: "Metal",
                        Fields.CHILDREN: [
                            {
                                Fields.ID: "Q120",
                                Fields.NAME_PUBLIC: "Heavy Metal",
                                Fields.CHILDREN: [
                                    {
                                        Fields.ID: "Q121",
                                        Fields.NAME_PUBLIC: "Classic Metal",
                                        Fields.CHILDREN: [
                                            {Fields.ID: "Q106", Fields.NAME_PUBLIC: "Power Metal", Fields.CHILDREN: []}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            self._mainstream_pop_root(),
        ]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: data}
        )
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.count() == 6
        rock = genres.get(name="Rock")
        metal = genres.get(name="Metal")
        heavy_metal = genres.get(name="Heavy Metal")
        classic_metal = genres.get(name="Classic Metal")
        power_metal = genres.get(name="Power Metal")
        assert rock is not None
        assert metal is not None
        assert heavy_metal is not None
        assert classic_metal is not None
        assert power_metal is not None
        assert rock.parent is None
        assert metal.parent.pk == rock.pk
        assert heavy_metal.parent.pk == metal.pk
        assert classic_metal.parent.pk == heavy_metal.pk
        assert power_metal.parent.pk == classic_metal.pk

    def test_multiple_children_then_ok(self):
        data = [
            {
                Fields.ID: "Q122",
                Fields.NAME_PUBLIC: "Rock",
                Fields.CHILDREN: [
                    {Fields.ID: "Q107", Fields.NAME_PUBLIC: "Metal", Fields.CHILDREN: []},
                    {Fields.ID: "Q108", Fields.NAME_PUBLIC: "Punk", Fields.CHILDREN: []},
                    {Fields.ID: "Q109", Fields.NAME_PUBLIC: "Blues", Fields.CHILDREN: []},
                ],
            },
            self._mainstream_pop_root(),
        ]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: data}
        )
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.count() == 5
        rock = genres.get(name="Rock")
        metal = genres.get(name="Metal")
        punk = genres.get(name="Punk")
        blues = genres.get(name="Blues")
        assert rock is not None
        assert metal is not None
        assert punk is not None
        assert blues is not None
        assert rock.parent is None
        assert metal.parent.pk == rock.pk
        assert punk.parent.pk == rock.pk
        assert blues.parent.pk == rock.pk

    def test_complex_structure_then_ok(self):
        data = [
            {
                Fields.ID: "Q123",
                Fields.NAME_PUBLIC: "Rock",
                Fields.CHILDREN: [
                    {
                        Fields.ID: "Q124",
                        Fields.NAME_PUBLIC: "Metal",
                        Fields.CHILDREN: [
                            {Fields.ID: "Q110", Fields.NAME_PUBLIC: "Heavy Metal", Fields.CHILDREN: []},
                            {Fields.ID: "Q111", Fields.NAME_PUBLIC: "Death Metal", Fields.CHILDREN: []},
                        ],
                    },
                    {
                        Fields.ID: "Q125",
                        Fields.NAME_PUBLIC: "Punk",
                        Fields.CHILDREN: [
                            {Fields.ID: "Q112", Fields.NAME_PUBLIC: "Hardcore", Fields.CHILDREN: []},
                            {Fields.ID: "Q113", Fields.NAME_PUBLIC: "Pop Punk", Fields.CHILDREN: []},
                        ],
                    },
                ],
            },
            {
                Fields.ID: "Q126",
                Fields.NAME_PUBLIC: "Jazz",
                Fields.CHILDREN: [
                    {Fields.ID: "Q114", Fields.NAME_PUBLIC: "Bebop", Fields.CHILDREN: []},
                    {Fields.ID: "Q115", Fields.NAME_PUBLIC: "Fusion", Fields.CHILDREN: []},
                ],
            },
            self._mainstream_pop_root(),
        ]
        response = self._post_genres_tree_import(
            data={Fields.ALLOWS_MULTIPLE_PRIMARY_PARENTS: False, Fields.TREE: data}
        )
        assert response.status_code == status.HTTP_201_CREATED

        genres = Genre.objects.filter(user=None)
        assert genres.count() == 11
        rock = genres.get(name="Rock")
        metal = genres.get(name="Metal")
        heavy_metal = genres.get(name="Heavy Metal")
        death_metal = genres.get(name="Death Metal")
        punk = genres.get(name="Punk")
        hardcore = genres.get(name="Hardcore")
        pop_punk = genres.get(name="Pop Punk")
        jazz = genres.get(name="Jazz")
        bebop = genres.get(name="Bebop")
        fusion = genres.get(name="Fusion")
        assert rock is not None
        assert metal is not None
        assert heavy_metal is not None
        assert death_metal is not None
        assert punk is not None
        assert hardcore is not None
        assert pop_punk is not None
        assert jazz is not None
        assert bebop is not None
        assert fusion is not None
        assert rock.parent is None
        assert metal.parent.pk == rock.pk
        assert heavy_metal.parent.pk == metal.pk
        assert death_metal.parent.pk == metal.pk
        assert punk.parent.pk == rock.pk
        assert hardcore.parent.pk == punk.pk
        assert pop_punk.parent.pk == punk.pk
        assert jazz.parent is None
        assert bebop.parent.pk == jazz.pk
        assert fusion.parent.pk == jazz.pk
