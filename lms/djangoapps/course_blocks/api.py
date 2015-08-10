"""
...
"""
from django.conf import settings
from django.core.cache import get_cache

from openedx.core.lib.block_cache.block_cache import get_blocks, clear_block_cache
from xmodule.modulestore.django import modulestore

from transformers import start_date, user_partitions, visibility
from user_info import CourseUserInfo


LMS_COURSE_TRANSFORMERS = {
    visibility.VisibilityTransformer(),
    start_date.StartDateTransformer(),
    user_partitions.UserPartitionTransformer(),
}

_cache = None
def _get_cache():
    global _cache
    if not _cache:
        _cache = get_cache('lms.course_blocks')
    return _cache


def get_course_blocks(
        user,
        course_key,
        root_usage_key,
        transformers=LMS_COURSE_TRANSFORMERS,
):
    if transformers is None:
        transformers = settings.LMS_COURSE_TRANSFORMERS

    return get_blocks(
        _get_cache(), modulestore(), CourseUserInfo(course_key, user), root_usage_key, transformers,
    )


def clear_course_from_cache(course_key):
    return clear_block_cache(_get_cache(), course_key.location)
