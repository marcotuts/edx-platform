"""
Tests for users API
"""
import datetime
import ddt
from mock import patch
import pytz

from django.conf import settings
from django.utils import timezone
from django.template import defaultfilters

from certificates.models import CertificateStatuses
from certificates.tests.factories import GeneratedCertificateFactory
from courseware.access_response import (
    MilestoneError,
    StartDateError,
    VisibilityError,
)
from student.models import CourseEnrollment
from util.milestones_helpers import (
    set_prerequisite_courses,
    seed_milestone_relationship_types,
)
from xmodule.course_module import DEFAULT_START_DATE
from xmodule.modulestore.tests.factories import ItemFactory, CourseFactory

from .. import errors
from ..testutils import MobileAPITestCase, MobileAuthTestMixin, MobileAuthUserTestMixin, MobileCourseAccessTestMixin
from .serializers import CourseEnrollmentSerializer


class TestUserDetailApi(MobileAPITestCase, MobileAuthUserTestMixin):
    """
    Tests for /api/mobile/v0.5/users/<user_name>...
    """
    REVERSE_INFO = {'name': 'user-detail', 'params': ['username']}

    def test_success(self):
        self.login()

        response = self.api_response()
        self.assertEqual(response.data['username'], self.user.username)
        self.assertEqual(response.data['email'], self.user.email)


class TestUserInfoApi(MobileAPITestCase, MobileAuthTestMixin):
    """
    Tests for /api/mobile/v0.5/my_user_info
    """
    def reverse_url(self, reverse_args=None, **kwargs):
        return '/api/mobile/v0.5/my_user_info'

    def test_success(self):
        """Verify the endpoint redirects to the user detail endpoint"""
        self.login()

        response = self.api_response(expected_response_code=302)
        self.assertTrue(self.username in response['location'])


@ddt.ddt
class TestUserEnrollmentApi(MobileAPITestCase, MobileAuthUserTestMixin):
    """
    Tests for /api/mobile/v0.5/users/<user_name>/course_enrollments/
    """
    REVERSE_INFO = {'name': 'courseenrollment-detail', 'params': ['username']}
    ALLOW_ACCESS_TO_UNRELEASED_COURSE = True
    ALLOW_ACCESS_TO_MILESTONE_COURSE = True
    NEXT_WEEK = datetime.datetime.now(pytz.UTC) + datetime.timedelta(days=7)
    LAST_WEEK = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=7)
    ADVERTISED_START = "Spring 2016"

    def verify_success(self, response):
        super(TestUserEnrollmentApi, self).verify_success(response)
        courses = response.data
        self.assertEqual(len(courses), 1)

        found_course = courses[0]['course']
        self.assertTrue('video_outline' in found_course)
        self.assertTrue('course_handouts' in found_course)
        self.assertEqual(found_course['id'], unicode(self.course.id))
        self.assertEqual(courses[0]['mode'], 'honor')
        self.assertEqual(courses[0]['course']['subscription_id'], self.course.clean_id(padding_char='_'))

    def verify_failure(self, response):
        self.assertEqual(response.status_code, 200)
        courses = response.data
        self.assertEqual(len(courses), 0)

    def test_sort_order(self):
        self.login()

        num_courses = 3
        courses = []
        for course_index in range(num_courses):
            courses.append(CourseFactory.create(mobile_available=True))
            self.enroll(courses[course_index].id)

        # verify courses are returned in the order of enrollment, with most recently enrolled first.
        response = self.api_response()
        for course_index in range(num_courses):
            self.assertEqual(
                response.data[course_index]['course']['id'],
                unicode(courses[num_courses - course_index - 1].id)
            )

    @patch.dict(
        settings.FEATURES, {'ENABLE_PREREQUISITE_COURSES': True, 'MILESTONES_APP': True, 'DISABLE_START_DATES': False}
    )
    def test_courseware_access(self):
        seed_milestone_relationship_types()
        self.login()

        course_with_prereq = CourseFactory.create(start=self.LAST_WEEK, mobile_available=True)
        prerequisite_course = CourseFactory.create()
        set_prerequisite_courses(course_with_prereq.id, [unicode(prerequisite_course.id)])

        # Create list of courses with various expected courseware_access responses and corresponding expected codes
        courses = [
            course_with_prereq,
            CourseFactory.create(start=self.NEXT_WEEK, mobile_available=True),
            CourseFactory.create(visible_to_staff_only=True, mobile_available=True),
            CourseFactory.create(start=self.LAST_WEEK, mobile_available=True, visible_to_staff_only=False),
        ]

        expected_error_codes = [
            MilestoneError().error_code,  # 'unfulfilled_milestones'
            StartDateError(self.NEXT_WEEK).error_code,  # 'course_not_started'
            VisibilityError().error_code,  # 'not_visible_to_user'
            None,
        ]

        # Enroll in all the courses
        for course in courses:
            self.enroll(course.id)

        # Verify courses have the correct response through error code. Last enrolled course is first course in response
        response = self.api_response()
        for course_index in range(len(courses)):
            result = response.data[course_index]['course']['courseware_access']
            self.assertEqual(result['error_code'], expected_error_codes[::-1][course_index])

            if result['error_code'] is not None:
                self.assertFalse(result['has_access'])

    @ddt.data(
        (NEXT_WEEK, ADVERTISED_START, ADVERTISED_START, "string"),
        (NEXT_WEEK, None, '', "string"),
        (DEFAULT_START_DATE, ADVERTISED_START, ADVERTISED_START, "string"),
        (DEFAULT_START_DATE, None, '', "string")
    )
    @ddt.unpack
    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_start_type_and_display(self, start, advertised_start, expected_display, expected_type):
        """
        Tests that the correct start_type and start_display are returned in the
        case the course has not started
        """
        self.login()
        course = CourseFactory.create(start=start, advertised_start=advertised_start, mobile_available=True)
        self.enroll(course.id)

        response = self.api_response()
        self.assertEqual(response.data[0]['course']['start_type'], expected_type)
        self.assertEqual(response.data[0]['course']['start_display'], expected_display)

    def test_no_certificate(self):
        self.login_and_enroll()

        response = self.api_response()
        certificate_data = response.data[0]['certificate']
        self.assertDictEqual(certificate_data, {})

    def test_certificate(self):
        self.login_and_enroll()

        certificate_url = "http://test_certificate_url"
        GeneratedCertificateFactory.create(
            user=self.user,
            course_id=self.course.id,
            status=CertificateStatuses.downloadable,
            mode='verified',
            download_url=certificate_url,
        )

        response = self.api_response()
        certificate_data = response.data[0]['certificate']
        self.assertEquals(certificate_data['url'], certificate_url)

    def test_no_facebook_url(self):
        self.login_and_enroll()

        response = self.api_response()
        course_data = response.data[0]['course']
        self.assertIsNone(course_data['social_urls']['facebook'])

    def test_facebook_url(self):
        self.login_and_enroll()

        self.course.facebook_url = "http://facebook.com/test_group_page"
        self.store.update_item(self.course, self.user.id)

        response = self.api_response()
        course_data = response.data[0]['course']
        self.assertEquals(course_data['social_urls']['facebook'], self.course.facebook_url)


class CourseStatusAPITestCase(MobileAPITestCase):
    """
    Base test class for /api/mobile/v0.5/users/<user_name>/course_status_info/{course_id}
    """
    REVERSE_INFO = {'name': 'user-course-status', 'params': ['username', 'course_id']}

    def setUp(self):
        """
        Creates a basic course structure for our course
        """
        super(CourseStatusAPITestCase, self).setUp()

        self.section = ItemFactory.create(
            parent=self.course,
            category='chapter',
        )
        self.sub_section = ItemFactory.create(
            parent=self.section,
            category='sequential',
        )
        self.unit = ItemFactory.create(
            parent=self.sub_section,
            category='vertical',
        )
        self.other_sub_section = ItemFactory.create(
            parent=self.section,
            category='sequential',
        )
        self.other_unit = ItemFactory.create(
            parent=self.other_sub_section,
            category='vertical',
        )


class TestCourseStatusGET(CourseStatusAPITestCase, MobileAuthUserTestMixin, MobileCourseAccessTestMixin):
    """
    Tests for GET of /api/mobile/v0.5/users/<user_name>/course_status_info/{course_id}
    """
    def test_success(self):
        self.login_and_enroll()

        response = self.api_response()
        self.assertEqual(
            response.data["last_visited_module_id"],
            unicode(self.sub_section.location)
        )
        self.assertEqual(
            response.data["last_visited_module_path"],
            [unicode(module.location) for module in [self.sub_section, self.section, self.course]]
        )


class TestCourseStatusPATCH(CourseStatusAPITestCase, MobileAuthUserTestMixin, MobileCourseAccessTestMixin):
    """
    Tests for PATCH of /api/mobile/v0.5/users/<user_name>/course_status_info/{course_id}
    """
    def url_method(self, url, **kwargs):
        # override implementation to use PATCH method.
        return self.client.patch(url, data=kwargs.get('data', None))  # pylint: disable=no-member

    def test_success(self):
        self.login_and_enroll()
        response = self.api_response(data={"last_visited_module_id": unicode(self.other_unit.location)})
        self.assertEqual(
            response.data["last_visited_module_id"],
            unicode(self.other_sub_section.location)
        )

    def test_invalid_module(self):
        self.login_and_enroll()
        response = self.api_response(data={"last_visited_module_id": "abc"}, expected_response_code=400)
        self.assertEqual(
            response.data,
            errors.ERROR_INVALID_MODULE_ID
        )

    def test_nonexistent_module(self):
        self.login_and_enroll()
        non_existent_key = self.course.id.make_usage_key('video', 'non-existent')
        response = self.api_response(data={"last_visited_module_id": non_existent_key}, expected_response_code=400)
        self.assertEqual(
            response.data,
            errors.ERROR_INVALID_MODULE_ID
        )

    def test_no_timezone(self):
        self.login_and_enroll()
        past_date = datetime.datetime.now()
        response = self.api_response(
            data={
                "last_visited_module_id": unicode(self.other_unit.location),
                "modification_date": past_date.isoformat()
            },
            expected_response_code=400
        )
        self.assertEqual(
            response.data,
            errors.ERROR_INVALID_MODIFICATION_DATE
        )

    def _date_sync(self, date, initial_unit, update_unit, expected_subsection):
        """
        Helper for test cases that use a modification to decide whether
        to update the course status
        """
        self.login_and_enroll()

        # save something so we have an initial date
        self.api_response(data={"last_visited_module_id": unicode(initial_unit.location)})

        # now actually update it
        response = self.api_response(
            data={
                "last_visited_module_id": unicode(update_unit.location),
                "modification_date": date.isoformat()
            }
        )
        self.assertEqual(
            response.data["last_visited_module_id"],
            unicode(expected_subsection.location)
        )

    def test_old_date(self):
        self.login_and_enroll()
        date = timezone.now() + datetime.timedelta(days=-100)
        self._date_sync(date, self.unit, self.other_unit, self.sub_section)

    def test_new_date(self):
        self.login_and_enroll()
        date = timezone.now() + datetime.timedelta(days=100)
        self._date_sync(date, self.unit, self.other_unit, self.other_sub_section)

    def test_no_initial_date(self):
        self.login_and_enroll()
        response = self.api_response(
            data={
                "last_visited_module_id": unicode(self.other_unit.location),
                "modification_date": timezone.now().isoformat()
            }
        )
        self.assertEqual(
            response.data["last_visited_module_id"],
            unicode(self.other_sub_section.location)
        )

    def test_invalid_date(self):
        self.login_and_enroll()
        response = self.api_response(data={"modification_date": "abc"}, expected_response_code=400)
        self.assertEqual(
            response.data,
            errors.ERROR_INVALID_MODIFICATION_DATE
        )


class TestCourseEnrollmentSerializer(MobileAPITestCase):
    """
    Test the course enrollment serializer
    """
    def test_success(self):
        self.login_and_enroll()

        serialized = CourseEnrollmentSerializer(CourseEnrollment.enrollments_for_user(self.user)[0]).data
        self.assertEqual(serialized['course']['video_outline'], None)
        self.assertEqual(serialized['course']['name'], self.course.display_name)
        self.assertEqual(serialized['course']['number'], self.course.id.course)
        self.assertEqual(serialized['course']['org'], self.course.id.org)

    def test_with_display_overrides(self):
        self.login_and_enroll()

        self.course.display_coursenumber = "overridden_number"
        self.course.display_organization = "overridden_org"
        self.store.update_item(self.course, self.user.id)

        serialized = CourseEnrollmentSerializer(CourseEnrollment.enrollments_for_user(self.user)[0]).data
        self.assertEqual(serialized['course']['number'], self.course.display_coursenumber)
        self.assertEqual(serialized['course']['org'], self.course.display_organization)
