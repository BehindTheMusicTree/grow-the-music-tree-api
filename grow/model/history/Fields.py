from the_music_tree_api_kit.private_unique_resource.Fields import Fields as PrivateUniqueResourceFields

from grow.model.ContentObjectFields import ContentObjectFields


class Fields(PrivateUniqueResourceFields, ContentObjectFields):
    ACTION = "action"
    ACTOR_EMAIL = "actor_email"
    OLD_VALUE = "old_value"
    NEW_VALUE = "new_value"
