from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateStorage(FileSystemStorage):
    """Files under MEDIA_ROOT with no public URL; they are served only by authenticated views."""

    def url(self, name):
        raise ValueError("Private files have no public URL.")
