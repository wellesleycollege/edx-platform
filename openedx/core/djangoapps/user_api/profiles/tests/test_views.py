import unittest
import ddt

from django.core.urlresolvers import reverse
from django.conf import settings

from openedx.core.djangoapps.user_api.accounts.tests.test_views import UserAPITestCase
from openedx.core.djangoapps.user_api.models import UserPreference
from openedx.core.djangoapps.user_api.profiles import PROFILE_VISIBILITY_PREF_KEY

TEST_PASSWORD = "test"


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class TestProfileAPI(UserAPITestCase):

    def setUp(self):
        super(TestProfileAPI, self).setUp()
        self.url = reverse("profiles_api", kwargs={'username': self.user.username})

    def test_get_profile_anonymous_user(self):
        """
        Test that an anonymous client (not logged in) cannot call get.
        """
        self.send_get(self.anonymous_client, expected_status=401)

    def test_get_profile_different_user(self):
        """
        Test that a logged in user can access the public profile for a different user.
        """
        self.different_client.login(username=self.different_user.username, password=TEST_PASSWORD)
        response = self.send_get(self.different_client)
        data = response.data
        self.assertEqual(6, len(data))
        self.assertEqual(self.user.username, data["username"])
        self.assertIsNone(data["profile_image"])
        self.assertIsNone(data["country"])
        self.assertIsNone(data["time_zone"])
        self.assertIsNone(data["languages"])
        self.assertIsNone(data["bio"])

    def test_get_profile_default(self):
        """
        Test that a logged in user can get her own public profile information.
        """
        self.client.login(username=self.user.username, password=TEST_PASSWORD)
        response = self.send_get(self.client)
        data = response.data
        self.assertEqual(6, len(data))
        self.assertEqual(self.user.username, data["username"])
        self.assertIsNone(data["profile_image"])
        self.assertIsNone(data["country"])
        self.assertIsNone(data["time_zone"])
        self.assertIsNone(data["languages"])
        self.assertIsNone(data["bio"])

    def test_get_private_profile(self):
        """
        Test that a logged in user can get her own private profile information.
        """
        self.client.login(username=self.user.username, password=TEST_PASSWORD)
        UserPreference.set_preference(self.user, PROFILE_VISIBILITY_PREF_KEY, 'private')
        response = self.send_get(self.client)
        data = response.data
        self.assertEqual(2, len(data))
        self.assertEqual(self.user.username, data["username"])
        self.assertIsNone(data["profile_image"])
