from rest_framework import serializers

from grow.model.recording.Recording import Recording

from .RecordingOutputFieldKey import RecordingOutputFieldKey


class RecordingMinimumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recording
        fields = [RecordingOutputFieldKey.UUID.value, RecordingOutputFieldKey.TITLE.value]
