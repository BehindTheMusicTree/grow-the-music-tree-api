from django.apps import AppConfig


class GrowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "grow"

    def ready(self):
        import grow.model.user.signals
        from grow.model.track.bootstrap import install_track_convenience_methods

        install_track_convenience_methods()
