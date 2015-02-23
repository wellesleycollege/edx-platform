"""
Tests for cleanup of users which are added in multiple cohorts of a course
"""
from django.core.exceptions import MultipleObjectsReturned
from django.core.management import call_command
from django.test.client import RequestFactory

from openedx.core.djangoapps.course_groups.views import cohort_handler
from openedx.core.djangoapps.course_groups.cohorts import get_cohort, get_cohort_by_name
from openedx.core.djangoapps.course_groups.tests.helpers import config_course_cohorts
from student.tests.factories import UserFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory


class TestMultipleCohortUsers(ModuleStoreTestCase):
    """
    Base class for testing users with multiple cohorts
    """
    def setUp(self):
        """
        setup course, user and request for tests
        """
        super(TestMultipleCohortUsers, self).setUp()
        self.course = CourseFactory.create()
        self.user = UserFactory(is_staff=True)
        self.request = RequestFactory().get("dummy_url")
        self.request.user = self.user

    def test_users_with_multiple_cohorts_cleanup(self):
        """
        Test that user which have been added in multiple cohorts of a course,
        can get cohorts without error after running cohorts cleanup command
        """
        # set two auto_cohort_groups
        config_course_cohorts(
            self.course, [], cohorted=True, auto_cohort_groups=["AutoGroup1", "AutoGroup2"]
        )

        # get the cohorts from the course, which will cause auto cohorts to be created.
        cohort_handler(self.request, unicode(self.course.id))
        auto_cohort_1 = get_cohort_by_name(self.course.id, "AutoGroup1")
        auto_cohort_2 = get_cohort_by_name(self.course.id, "AutoGroup2")

        # forcefully add user in two auto cohorts
        auto_cohort_1.users.add(self.user)
        auto_cohort_2.users.add(self.user)

        # now check that when user goes on discussion page and tries to get
        # cohorts 'MultipleObjectsReturned' exception is returned
        with self.assertRaises(MultipleObjectsReturned):
            get_cohort(self.user, self.course.id)

        # call command to remove users added in multiple cohorts of a course
        # are removed from all cohort groups
        call_command('remove_users_from_multiple_cohorts')

        # now check that user can get cohorts in which he is added
        response = cohort_handler(self.request, unicode(self.course.id))
        self.assertEqual(response.status_code, 200)
