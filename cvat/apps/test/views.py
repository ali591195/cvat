# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from cvat.apps.engine.models import Job, Task
from cvat.apps.engine.types import ExtendedRequest
from cvat.utils import django_database as db_utils

from .counts import count_annotations_by_label
from .live import TICKET_MAX_AGE, make_ticket
from .permissions import LabelCountsPermission
from .serializers import (
    LabelCountsQuerySerializer,
    LabelCountsSerializer,
    LabelCountsTicketQuerySerializer,
    LabelCountsTicketSerializer,
)


@extend_schema(tags=["label-counts"])
class LabelCountsViewSet(viewsets.ViewSet):
    # The result is not a list of organization resources: the organization
    # is taken from the task, so the organization parameters have no effect
    iam_supports_organization_params = False
    iam_permission_class = LabelCountsPermission

    @extend_schema(
        summary="Get the number of annotations per label in a task",
        parameters=[LabelCountsQuerySerializer],
        responses={"200": LabelCountsSerializer},
    )
    def list(self, request: ExtendedRequest):
        query = LabelCountsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        task = db_utils.get_or_404(
            Task.objects.select_related("data"), query.validated_data["task_id"]
        )

        job = None
        if (job_id := query.validated_data.get("job_id")) is not None:
            job = Job.objects.filter(segment__task_id=task.id, id=job_id).first()
            if job is None:
                raise ValidationError(
                    {"job_id": [f"Job {job_id} does not belong to task {task.id}"]}
                )

        labels = count_annotations_by_label(task, job=job)
        response = LabelCountsSerializer(
            {
                "task_id": task.id,
                "job_id": job.id if job else None,
                "total": sum(label["count"] for label in labels),
                "labels": labels,
            }
        )
        return Response(response.data)

    @extend_schema(
        summary="Get a ticket to open the live label counts WebSocket for a task",
        description=(
            "Connect to WS /api/label-counts/live?ticket=<ticket> to be told "
            "when annotations of the task change."
        ),
        parameters=[LabelCountsTicketQuerySerializer],
        responses={"200": LabelCountsTicketSerializer},
    )
    @action(detail=False, methods=["GET"], url_path="live-ticket")
    def live_ticket(self, request: ExtendedRequest):
        query = LabelCountsTicketQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        task_id = query.validated_data["task_id"]

        ticket = LabelCountsTicketSerializer(
            {"ticket": make_ticket(request.user.id, task_id), "expires_in": TICKET_MAX_AGE}
        )
        return Response(ticket.data)
