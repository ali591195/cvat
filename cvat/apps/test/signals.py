# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_rq.queues import get_redis_connection

from cvat.apps.engine.models import Job

from .live import get_channel


@receiver(post_save, sender=Job, dispatch_uid="label_counts_publish_changes")
def publish_annotations_changed(sender, instance: Job, update_fields, **kwargs):
    # CVAT touches the job (a save of updated_date only) after each change of its annotations
    if not update_fields or "updated_date" not in update_fields:
        return

    channel = get_channel(instance.segment.task_id)
    transaction.on_commit(
        lambda: get_redis_connection(settings.REDIS_INMEM_SETTINGS).publish(channel, "changed")
    )
