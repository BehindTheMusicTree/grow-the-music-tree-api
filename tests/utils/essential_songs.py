from django.db.models import Max

from grow.model.criteria.children.genre.GenreEssentialSong import GenreEssentialSong


def add_essential_song(genre, song) -> None:
    """Appends `song` to the genre's ordered essential songs."""
    last = GenreEssentialSong.objects.filter(genre=genre).aggregate(last=Max("position"))["last"] or 0
    GenreEssentialSong.objects.create(genre=genre, song=song, position=last + 1)
